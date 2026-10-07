ARG BROWSER=chrome
FROM python:3.13.11-slim-trixie AS python-base

# Name of the chrome profile inside static_resources
ENV CHROME_PROFILE_NAME=chrome_profile_2024_06_30.tar.gz

# Python ENV vars, valid in all images that use 'FROM python-base'
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=on \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_NO_INTERACTION=1 \
    DEBIAN_FRONTEND=noninteractive \
    APP_PATH=/crawler \
    NODE_MAJOR=18 \
    SETUP_PATH=/opt \
    LANG=C.UTF-8 \
    TZ=Europe/Zurich

# Based on the ones above
ENV VIRTUAL_ENV=$SETUP_PATH/venv \
    PATH=$SETUP_PATH/venv/bin:$PATH \
    NODE_PATH=$SETUP_PATH/node_modules \
    CRAWLER_PP_CLASSIFIER_PATH=$SETUP_PATH/pp_classifier/

WORKDIR $SETUP_PATH

# Install running dependecies
RUN apt-get update && \
    apt-get install --no-install-recommends -y ca-certificates gnupg curl libpq5 dnsutils libprotobuf-dev vim iproute2 pbzip2 xz-utils bzip2 libicu-dev xvfb

# ubuntu only has node version 12.x (So we install it from scratch)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - &&\
    apt-get update && \
    apt-get install -y nodejs && \
    pip install poetry wheel && \
    python -m venv "$VIRTUAL_ENV"

FROM python-base AS builder

# install build dependencies
RUN apt-get update && \
    apt-get install --no-install-recommends -y build-essential git pkg-config libpq-dev \
                      libprotobuf-c-dev protobuf-compiler protobuf-c-compiler \
                      libprotobuf-dev protobuf-compiler libprotobuf-dev rsync

# We copy our Python requirements here to cache them
# and install only runtime deps using poetry
# ONLY $SETUP_PATH will be used afterwards from this 'builder' image

COPY ./poetry.lock ./pyproject.toml ./interceptor/package.json ./interceptor/package-lock.json ./

RUN . $VIRTUAL_ENV/bin/activate && \
    poetry install --only main --no-root && \
    python3 -m spacy download de_core_news_md && \
    python3 -m spacy download en_core_web_md && \
    python3 -m nltk.downloader stopwords && \
    npm install

FROM python-base AS chrome

COPY ./static_resources/$CHROME_PROFILE_NAME $SETUP_PATH/static_resources/

ENV CHROME_PROFILE_PATH=$SETUP_PATH"/static_resources/"$CHROME_PROFILE_NAME \
    CRAWLER_CHROME_DRIVER_PATH="${SETUP_PATH}/chromedriver/chromedriver" \
    CRAWLER_CHROME_PROFILE_PATH="${SETUP_PATH}/chrome_profile" \
    CRAWLER_CHROME_BROWSER_PATH="${SETUP_PATH}/chrome/chrome" \
    CRAWLER_BROWSER="chrome"

COPY ./scripts/install_chrome.sh /crawler/scripts/

# install chromium version XXX to /opt/{chrome,chromedriver}
RUN apt-get update && \
    apt-get install --no-install-recommends -y wget unzip chromium && \
    /crawler/scripts/install_chrome.sh /opt/ && \
    apt-get remove -y chromium && \
    tar xvz --no-same-permissions -f $CHROME_PROFILE_PATH -C $SETUP_PATH

# These are copied away
RUN rm -rf $SETUP_PATH/static_resources/

FROM python-base AS firefox
ENV FIREFOX_PROFILE_NAME=firefox_profile_31032022.tar.gz

COPY ./static_resources/$FIREFOX_PROFILE_NAME $SETUP_PATH/static_resources/

ENV FIREFOX_PROFILE_PATH=$SETUP_PATH"/static_resources/"$FIREFOX_PROFILE_NAME \
    GECKO_DRIVER_VERSION="v0.30.0" \
    CRAWLER_GECKO_DRIVER_PATH="$SETUP_PATH/geckodriver" \
    CRAWLER_FIREFOX_PROFILE_PATH="$SETUP_PATH/firefox_profile" \
    CRAWLER_BROWSER="firefox"

RUN apt-get update && \
    apt-get install --no-install-recommends -y firefox-esr && \
    curl -sL https://github.com/mozilla/geckodriver/releases/download/$GECKO_DRIVER_VERSION/geckodriver-$GECKO_DRIVER_VERSION-linux64.tar.gz | tar xvz -C $SETUP_PATH && \
    tar xvz --no-same-permissions -f $FIREFOX_PROFILE_PATH -C $SETUP_PATH

# These are copied away
RUN rm -rf $SETUP_PATH/static_resources/

# Development image (if built with --target development) contains the dev dependencies of pyproject.toml too
FROM $BROWSER AS development

# development version needs build packages
RUN apt-get update && \
    apt-get install --no-install-recommends -y build-essential git pkg-config libpq-dev python3-dev

# Copy over compiled dependencies in virtualenv
COPY --from=builder $SETUP_PATH $SETUP_PATH

# Copy crawler code and install local pip package
COPY . $APP_PATH

WORKDIR $APP_PATH

# Install all dependencies, update the chrome profile, install readabilipy and kill chrome - if still running
RUN poetry install && \
    . $VIRTUAL_ENV/bin/activate && \
    poetry cache clear --all -n . && \
    $APP_PATH/enfbots_crawler/scripts/update_chromeprofile.py --profile-path $SETUP_PATH/chrome_profile && \
    enfbot --install-readabilipy && \
    pkill chrome || exit 0

# Production image contains only what is needed to run
FROM $BROWSER AS production

# Copy over compiled dependencies in virtualenv
COPY --from=builder $SETUP_PATH $SETUP_PATH

# Copy crawler code and install local pip package
COPY . $APP_PATH

WORKDIR $APP_PATH

# Install all dependencies, update the chrome profile, install readabilipy and kill chrome - if still running
RUN . $VIRTUAL_ENV/bin/activate && \
    poetry cache clear --all -n . && \
    poetry install --only main && \
    $APP_PATH/enfbots_crawler/scripts/update_chromeprofile.py --profile-path $SETUP_PATH/chrome_profile && \
    enfbot --install-readabilipy && \
    rm -rf static_resources && \
    pkill chrome || exit 0
