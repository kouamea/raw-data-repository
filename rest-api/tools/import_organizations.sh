#!/bin/bash -e

# Upserts awardees, organizations, and/or sites from CSV input files in the data dir

USAGE="tools/import_organizations.sh [--account <USER>@pmi-ops.org --project <PROJECT>] [--dry_run]"

while true; do
  case "$1" in
    --account) ACCOUNT=$2; shift 2;;
    --project) PROJECT=$2; shift 2;;
    --dry_run) DRY_RUN=--dry_run; shift 1;;
    --use_fixture_data) USE_FIXTURES=true; shift 1;;
    -- ) shift; break ;;
    * ) break ;;
  esac
done
if [ -z "${ACCOUNT}" ]  && [ "${PROJECT}" ];
then
  echo "Usage: $USAGE"
  exit 1
fi

TMP_GEOCODE_DIR=$(mktemp -d)
TMP_GEOCODE_INFO_FILE=${TMP_GEOCODE_DIR}/geocode_key.json

function cleanup {
:
}

function get_geocode_key {
    echo "Getting geocode api key ..."
    (tools/install_config.sh --key geocode_key --account "${ACCOUNT}" \
	    --project "pmi-drc-api-test"  --config_output "$TMP_GEOCODE_INFO_FILE")
    export API_KEY=$(cat $TMP_GEOCODE_INFO_FILE | python -c 'import json,sys;obj=json.load(sys.stdin);print obj["'api_key'"]')
}

CREDS_ACCOUNT="${ACCOUNT}"
if [ -z "${ACCOUNT}" ]
then
echo "Using stub geocoding when --account is not specified"
GEOCODE_FLAG=--stub_geocoding
else
get_geocode_key
fi

EXTRA_ARGS="$@"
if [ "${PROJECT}" ]
then
  echo "Getting credentials for ${PROJECT}..."
  source tools/auth_setup.sh
  run_cloud_sql_proxy
  set_db_connection_string
  EXTRA_ARGS+=" --creds_file ${CREDS_FILE} --instance ${INSTANCE} --project ${PROJECT}"
else
  if [ -z "${DB_CONNECTION_STRING}" ]
  then
    source tools/setup_local_vars.sh
    set_local_db_connection_string
  fi
fi

source tools/set_path.sh

if [[ ${USE_FIXTURES} = true ]];
then DATA_DIR=test/test-data/fixtures;
else DATA_DIR=data;
fi

python tools/import_organizations.py \
  --awardee_file ${DATA_DIR}/awardees.csv \
  --organization_file ${DATA_DIR}/organizations.csv \
  --site_file ${DATA_DIR}/sites.csv \
  $EXTRA_ARGS $DRY_RUN $GEOCODE_FLAG

function finish {
  cleanup
  rm -rf ${TMP_GEOCODE_DIR}
  rm -f ${TMP_GEOCODE_INFO_FILE}
}
trap finish EXIT

