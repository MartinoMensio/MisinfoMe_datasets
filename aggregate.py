#!/usr/bin/env python

# puts together all the datasets

import os
import json
import glob
import shutil
import signal
import sys
from dateutil import parser
from unidecode import unidecode
from collections import defaultdict
from pathlib import Path

import utils
import unshortener

import database_builder

def normalise_str(string):
    string = unidecode(string)
    string = string.lower()
    string = string.replace('"', '')
    string = string.replace('\'', '')
    string = string.replace('  ', ' ')
    return string

def select_best_candidate(fcu, matches):
    """Determine whether the fact_checking_url should be matched with any of the candidates, otherwise return None"""
    # the ones that pass the compulsory comparison
    matching_criteria = []
    affinities = []
    for m in matches:
        # the URL has been already compared
        if m['url'] == fcu['url']:
            matching_criteria.append(m)
            affinities.append(0)
    for idx, m in enumerate(matching_criteria):
        for k, v in fcu.items():
            if k == 'source':
                # the source has not to be compared
                continue
            if v and k in m and m[k]:
                prev = m[k]
                cur = v
                if k == 'claim':
                    # text normalisation
                    prev = normalise_str(prev)
                    cur = normalise_str(cur)
                if k == 'date':
                    prev = parser.parse(prev).date()
                    cur = parser.parse(cur).date()
                if k == 'original_label':
                    # ignore this property, too sensitive. There is already the 'label'
                    continue

                if prev != cur:
                    # if some values are different, this is a different claimReview
                    print(k, m['url'], v, m[k])
                    affinities[idx] = -50
                else:
                    affinities[idx] += 1

    # if len(matching_criteria):
    #     print(len(matching_criteria))
    #     print(affinities)
    #print([json.dump({k: v for k,v in el.items() if k != '_id'}, sys.stdout, indent=2) for el in matching_criteria])
    #exit(0)

    best = None
    best_affinity = -1
    for idx, (affinity, m) in enumerate(zip(affinities, matching_criteria)):
        if affinity >= 0:
            if affinity > best_affinity:
                best = m
                best_affinity = affinity

    # if best:
    #     print('going to merge', best, fcu)

    return best


def merge_fact_checking_urls(old, new):
    if not old:
        result = {**new}
        result['source'] = [new['source']]
    else:
        # TODO fields that cannot be merged
        #if new['source'] not in old['source']:
        if 'label' in new and 'label' in old and new['label'] != old['label']:
            if new['label'] != None and old['label'] != None:
                if new['claim'] != old['claim']:
                    raise ValueError('retry')
                    # TODO this will be fixed shortly
                else:
                    print(old)
                    print(new)
                    raise ValueError('abort')
        #result = {**old, **{k:v for k,v in new.items() if v!=None}}
        result = old
        print(old['source'], new['source'])
        for k,v in new.items():
            if k == 'source':
                result['source'] = list(set(old['source'] + [new['source']]))
            else:
                if v!=None and v != "":
                    result[k] = v
    return result

def merge_rebuttals(rebuttals_for_url, new_rebuttal):
    print(rebuttals_for_url, new_rebuttal)
    match = next((el for el in rebuttals_for_url if el['url'] == new_rebuttal['url']), None)
    if not match:
        match = {'url': new_rebuttal['url'], 'source': []}
        rebuttals_for_url.append(match)

    #print(match['source'])
    #print(match['source'])
    match['source'] = list(set(match['source'] + new_rebuttal['source']))

    return rebuttals_for_url


# decide here what to aggregate
choice = {k: {
    'urls': el['contains'].get('url_classification', False), # TODO rename to url_labels
    'domains': el['contains'].get('domain_classification', False), # TODO rename to domain_labels
    'rebuttals': el['contains'].get('rebuttal_suggestion', False), # TODO rename to rebuttals
    'claimReviews': el['contains'].get('claimReviews', False), # TODO rename to claim_reviews
    'fact_checking_urls': el['contains'].get('fact_checking_urls', False)
} for k, el in utils.read_json('sources.json')['datasets'].items()}

def aggregate_initial():
    all_urls = []
    all_domains = []
    all_rebuttals = defaultdict(list)
    all_claimreviews = []
    aggregated_fact_checking_urls = []
    all_fact_checking_urls_by_url = defaultdict(list)
    # step 1: load types of data natively
    for subfolder, config in choice.items():
        if config['urls']:
            urls = utils.read_json(utils.data_location / subfolder / 'urls.json')
            all_urls.extend(urls)
        if config['domains']:
            domains = utils.read_json(utils.data_location / subfolder / 'domains.json')
            all_domains.extend(domains)
        if config['rebuttals']:
            rebuttals = utils.read_json(utils.data_location / subfolder / 'rebuttals.json')
            for source_url, rebuttal_l in rebuttals.items():
                for rebuttal_url, source in rebuttal_l.items():
                    all_rebuttals[source_url] = merge_rebuttals(all_rebuttals.get(source_url, []), {'url': rebuttal_url, 'source': source})
        if config['claimReviews']:
            claimReview = utils.read_json(utils.data_location / subfolder / 'claimReviews.json')
            all_claimreviews.extend(claimReview)
        if config['fact_checking_urls']:
            fact_checking_urls = utils.read_json(utils.data_location / subfolder / 'fact_checking_urls.json')
            for fcu in fact_checking_urls:
                # mongo limits on indexed values
                fcu['url'] = fcu['url'][:1000]
                if fcu.get('claim_url', None): fcu['claim_url'][:1000]


                #matches = database_builder.get_fact_checking_urls(fcu['url'])
                matches = all_fact_checking_urls_by_url[fcu['url']]
                candidate = select_best_candidate(fcu, matches)
                merged = merge_fact_checking_urls(candidate, fcu)
                #database_builder.load_fact_checking_url(merged)
                all_fact_checking_urls_by_url[fcu['url']].append(merged)
                aggregated_fact_checking_urls.append(merged)

    # TODO

    urls_cnt = len(all_urls)
    domains_cnt = len(all_domains)
    fake_urls_cnt = len([el for el in all_urls if el['label'] == 'fake'])
    fake_domains_cnt = len([el for el in all_domains if el['label'] == 'fake'])
    print('before aggregation #urls', urls_cnt, ': fake', fake_urls_cnt, 'true', urls_cnt - fake_urls_cnt)
    print('before aggregation #domains', domains_cnt, ': fake', fake_domains_cnt, 'true', domains_cnt - fake_domains_cnt)

    aggregated_urls = utils.aggregate(all_urls)
    aggregated_domains = utils.aggregate(all_domains, 'domain')

    utils.write_json_with_path(aggregated_urls, utils.data_location, 'aggregated_urls.json')
    utils.write_json_with_path(aggregated_domains, utils.data_location, 'aggregated_domains.json')
    utils.write_json_with_path(all_rebuttals, utils.data_location, 'aggregated_rebuttals.json')
    utils.write_json_with_path(all_claimreviews, utils.data_location, 'aggregated_claimReviews.json')
    utils.write_json_with_path(aggregated_fact_checking_urls , utils.data_location, 'aggregated_fact_checking_urls.json')

    utils.print_stats(aggregated_urls)
    utils.print_stats(aggregated_domains)
    print('len aggregated fact_checking_urls', len(aggregated_fact_checking_urls))


    # database_builder.load_urls_zero()
    # database_builder.load_domains_zero()
    # database_builder.load_rebuttals_zero()

    to_be_mapped = [url for url in aggregated_urls.keys()]
    #unshortener.unshorten_multiprocess(to_be_mapped)

def load_into_db():
    # build the database
    # database_builder.clean_db()
    # database_builder.create_indexes()
    # database_builder.load_sources()
    # # load into database the beginning
    # database_builder.load_urls_zero(file_name='aggregated_urls_with_fcu.json')
    # database_builder.load_domains_zero()
    database_builder.load_rebuttals_zero(file_name='aggregated_rebuttals_with_fcu.json')
    # database_builder.load_fact_checking_urls_zero()

def check_and_add_url(new_url, new_label, new_sources, aggregated_urls):
    match = aggregated_urls.get('url', None)
    if match:
        print(match, new_url)
        exit(0)
        sources = match['sources']
        label = match['label']
        if label != new_label:
            raise ValueError('labels differ: old {} new {}'.format(label, new_label))
        sources += new_sources
    else:
        label = new_label
        sources = new_sources
    aggregated_urls[new_url] = {
        'label': label,
        'sources': sources
    }


def extract_more():
    """
    Extracts the additional informations:
    From fact_checking_urls:
    - if el['claim_url'] and el['label']: add url with label
    - if el['url']: add url with 'true' label (the fact checker is trustworthy??)
    """
    fact_checking_urls = utils.read_json(utils.data_location / 'aggregated_fact_checking_urls.json')
    classified_urls = utils.read_json(utils.data_location / 'aggregated_urls.json')
    rebuttals = utils.read_json(utils.data_location / 'aggregated_rebuttals.json')

    print('BEFORE extract_more')
    utils.print_stats(classified_urls)

    for fcu in fact_checking_urls:
        url = fcu.get('url', None)
        claim_url = fcu.get('claim_url', None)
        label = fcu.get('label', None)
        sources = fcu['source']
        if url and url != "":
            check_and_add_url(url, 'true', sources, classified_urls)
        if claim_url and label:
            check_and_add_url(claim_url, label, sources, classified_urls)
            if claim_url not in rebuttals:
                rebuttals[claim_url] = []
            rebuttals[claim_url] = merge_rebuttals(rebuttals.get(claim_url, []), {
                        'url': url,
                        'source': sources
                    })

    print('AFTER extract_more')
    utils.print_stats(classified_urls)

    utils.write_json_with_path(classified_urls, utils.data_location, 'aggregated_urls_with_fcu.json')
    utils.write_json_with_path(rebuttals, utils.data_location, 'aggregated_rebuttals_with_fcu.json')


if __name__ == "__main__":
    aggregate_initial()
    extract_more()
    load_into_db()
