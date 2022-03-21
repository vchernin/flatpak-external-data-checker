#!/bin/bash

if [[ -z "$GITHUB_WORKSPACE" || -z "$GITHUB_REPOSITORY" ]]; then
    echo "Script is not running in GitHub Actions CI"
    exit 1
fi

if [[ -z "$1" ]]; then
    echo "Config file (e.g. flathub.json) not found, will not read from any config files present in repositories"
else
    config_file=$1
fi

if [[ -z "$2" ]]; then
    echo "GitHub organization mode setting not found, assuming updating only an individual repository"
else
    github_org_wide=$2
fi

if [[ -z "$3" ]]; then
    echo "Was not passed a exact path to the Flatpak manifest. Exiting."
    exit 1
else
    path_to_manifest=$3
fi

detect_manifest() {
    repo=${1}
    
    # Todo whether run GitHub-org wide or for an individual repo, this should ideally search for manifests recursively.
    # There is no guarantee it is in the root directory.
    
    # todo maybe just make the path a required input option...
    # but need to be consistent for org-wide mode
    
    # this particular below logic is wrong, since apparently 
    # when in not-flathub we cannot rely on the above directory being the same name as the manifest
    
    # if [[ -f com.github.wwmm.easyeffects.yml ]]; then
    #     manifest=com.github.wwmm.easyeffects.yml
    # elif [[ -f com.github.wwmm.easyeffects.yaml ]]; then
    #     manifest=com.github.wwmm.easyeffects.yaml
    # elif [[ -f com.github.wwmm.easyeffects.json ]]; then
    #     manifest=com.github.wwmm.easyeffects.json
    # else
    #     return 1
    # fi

    echo $path_to_manifest
}

read_config() {
    
    FEDC_OPTS=()
    
    if [ -z ${config_file+x} ]; then 
        echo "config file variable was not set, no config options will be read from a file"
    else 
        echo "config file should exist, attempting to read it"; 
        ls
        if [[ -f $config_file ]]; then
        
            # todo these 2 checks are only for org mode, and uneeded for individual mode (probably?)
            # if ! jq -e '."disable-external-data-checker" | not' < $config_file > /dev/null; then
            #     return 1
            # fi
            # if ! jq -e '."end-of-life" or ."end-of-life-rebase" | not' < $config_file > /dev/null; then
            #     return 1
            # fi
            if ! jq -e '."require-important-update" | not' < $config_file > /dev/null; then
                FEDC_OPTS+=("--require-important-update")
            fi
            # todo this probably won't actually work yet, but is here for later
            if ! jq -e '."automerge-flathubbot-prs" | not' < $config_file > /dev/null; then
                FEDC_OPTS+=("--automerge-flathubbot-prs") 
            fi
        else
            echo "config file variable was set, but config file was not found"
        fi
    fi
    
}


git config --global user.name "$GIT_AUTHOR_NAME" && \
git config --global user.email "$GIT_AUTHOR_EMAIL"

if [ -z ${github_org_wide+x} ]; then 
    echo "GitHub organization mode variable is unset, assuming only need to edit individual current repo"; 
    checker_apps[0]=$(pwd)
else 
    # todo all the github-org wide code is basically untested
    echo "GitHub organization mode is being set, attempting to run for a GitHub organization" 
        
    # assumes the GitHub org follows the Flathub org's structute.
    # i.e., at github.com/$github_org_wide there will be several repos to check
    mkdir "$github_org_wide"
    cd "$github_org_wide"

    gh-ls-org "$github_org_wide" | parallel "git clone --depth 1 {}"
    mapfile -t checker_apps < <( grep -rl -E 'extra-data|x-checker-data|\.AppImage' | cut -d/ -f1 | sort -u )
fi

for repo in ${checker_apps[@]}; do
    manifest=$(detect_manifest "$repo")
    read_config
    if [[ -n $manifest ]]; then
        echo "==> checking ${repo}"
        /app/flatpak-external-data-checker --verbose "${FEDC_OPTS[@]}" --update --never-fork "$manifest"
    fi
done
