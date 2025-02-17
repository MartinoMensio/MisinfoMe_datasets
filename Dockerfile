FROM python:3.12.3-alpine as base
# move to edge, removes a lot of vulnerabilities
RUN sed -i -e 's/v[^/]*/edge/g' /etc/apk/repositories && \
    apk update && \
    apk upgrade && \
    apk add libgcc openblas libstdc++
# libgcc openblas libstdc++ are needed for jellifish that is built without static linking
WORKDIR /app



# builder stage
FROM base as builder

# install dependencies
RUN pip install pdm

# add cargo to be able to build jellyfish for musl
RUN apk --no-cache --update-cache add cargo

# add files for installation of dependencies
COPY pyproject.toml pdm.lock README.md /app/

# install scipy and numpy from anaconda wheels (support for musl).
# This requires creating virtualenv first. PDM will use this virtualenv
RUN virtualenv .venv && . .venv/bin/activate && pip install --pre -i https://pypi.anaconda.org/scipy-wheels-nightly/simple scipy numpy

# install pdm in .venv by default
RUN pdm install --prod --no-lock --no-editable

# remove pip and setuptools from .venv to remove vulnerabilities
RUN . .venv/bin/activate && pip uninstall setuptools pip -y



# production stage
FROM base as production
# pip and setuptools have open vulnerabilities, remove them
RUN pip uninstall setuptools pip -y

# files from builder
COPY --from=builder /app /app
# files from application
COPY claimreview_collector /app/claimreview_collector


# set environment and launch uvicorn
CMD . .venv/bin/activate && uvicorn claimreview_collector.main:app --host 0.0.0.0