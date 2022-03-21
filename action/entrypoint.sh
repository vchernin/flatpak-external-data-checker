#!/bin/bash

if [[ -z "$GITHUB_WORKSPACE" || -z "$GITHUB_REPOSITORY" ]]; then
    echo "Script is not running in GitHub Actions CI"
    exit 1
fi

if [[ -z "$MANIFEST_PATH" ]]; then
    echo "Was not passed a path to the Flatpak manifest. Exiting."
    exit 1
fi

if [[ -z "$GIT_AUTHOR_NAME" || -z "$GIT_AUTHOR_EMAIL" ]]; then
    echo "Github author name or Git author email did not exist."
fi


FEDC_OPTS=()

if [[ "$REQUIRE_IMPORTANT_UPDATE" == "true" ]]; then
    FEDC_OPTS+=("--require-important-update")
    echo "--require-important-update set and enabled."
fi

if [[ "$AUTOMERGE_FEDC_PRS" == "true" ]]; then
    FEDC_OPTS+=("--automerge-flathubbot-prs")
    echo "--automerge-flathubbot-prs set and enabled."
fi


git config --global user.name "$GIT_AUTHOR_NAME" && \
git config --global user.email "$GIT_AUTHOR_EMAIL"


echo "==> checking $(pwd)"
/app/flatpak-external-data-checker --verbose "${FEDC_OPTS[@]}" --update --never-fork "$MANIFEST_PATH"

