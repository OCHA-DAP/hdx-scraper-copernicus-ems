# Collector for Copernicus EMS Rapid Mapping Datasets
[![Build Status](https://github.com/OCHA-DAP/hdx-scraper-copernicus-ems/actions/workflows/run-python-tests.yaml/badge.svg)](https://github.com/OCHA-DAP/hdx-scraper-copernicus-ems/actions/workflows/run-python-tests.yaml)
[![Coverage Status](https://coveralls.io/repos/github/OCHA-DAP/hdx-scraper-copernicus-ems/badge.svg?branch=main&ts=1)](https://coveralls.io/github/OCHA-DAP/hdx-scraper-copernicus-ems?branch=main)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

This script reads the Copernicus Emergency Management Service (EMS) Rapid Mapping RSS
feed (`https://mapping.emergency.copernicus.eu/latest/feed/`) to discover new EMSR
activation codes, fetches per-activation detail from the EMS JSON API, and publishes
one HDX dataset per activation with the activation's full products archive as a
resource and a link to its StoryMap as a showcase.

There is no confirmed endpoint to list all activations, so the RSS feed (a small
rolling window of recent items) is the only discovery mechanism - this is a known
limitation, not a bug. Runs are incremental, tracked via `HDXState` against a
`pipeline-state-copernicus-ems` HDX dataset, which must exist before the first run
(see Deployment below).

## Development

### Environment

Development is currently done using Python 3.13. The environment can be created with:

```shell
    uv sync
```

This creates a .venv folder with the versions specified in the project's uv.lock file.

### Installing and running

For the script to run, you will need to have a file called
.hdx_configuration.yaml in your home directory containing your HDX key, e.g.:

    hdx_key: "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
    hdx_read_only: false
    hdx_site: prod

 You will also need to supply the universal .useragents.yaml file in your home
 directory as specified in the parameter *user_agent_config_yaml* passed to
 facade in run.py. The collector reads the key
 **hdx-scraper-copernicus-ems** as specified in the parameter
 *user_agent_lookup*.

 Alternatively, you can set up environment variables: `USER_AGENT`, `HDX_KEY`,
`HDX_SITE`, `EXTRA_PARAMS`, `TEMP_DIR`, and `LOG_FILE_ONLY`.

To run, execute:

```shell
    uv run python -m hdx.scraper.copernicus.ems
```

### Pre-commit

pre-commit will be installed when syncing uv. It is run every time you make a git
commit if you call it like this:

```shell
    pre-commit install
```

With pre-commit, all code is formatted according to
[ruff](https://docs.astral.sh/ruff/) guidelines.

To check if your changes pass pre-commit without committing, run:

```shell
    pre-commit run --all-files
```

## Packages

[uv](https://github.com/astral-sh/uv) is used for package management.  If
you’ve introduced a new package to the source code (i.e. anywhere in `src/`),
please add it to the `project.dependencies` section of `pyproject.toml` with
any known version constraints.

To add packages required only for testing, add them to the
`[dependency-groups]`.

Any changes to the dependencies will be automatically reflected in
`uv.lock` with `pre-commit`, but you can re-generate the files without committing by
executing:

```shell
    uv lock --upgrade
```

## Project

[uv](https://github.com/astral-sh/uv) is used for project management. The project can be
built using:

```shell
    uv build
```

Linting and syntax checking can be run with:

```shell
    uv run ruff check
```

To run the tests and view coverage, execute:

```shell
    uv run pytest
```

## Deployment

Before the first production run, an HDX dataset named `pipeline-state-copernicus-ems`
must exist with a single small text resource - `HDXState` reads/writes the
last-processed feed date to it and will error on `Dataset.read_from_hdx` if it doesn't
exist yet. This mirrors the bootstrap step used by other incrementally-tracked HDX
pipelines (e.g. `hdx-scraper-sentinelasia`).

**Note:** `dataset_maintainer`, `license_id`, `caveats`, and `notes` in
`config/hdx_dataset_static.yaml` are provisional placeholders pending confirmation
from DPT's Copernicus EMS metadata form - do not treat this pipeline as ready to
deploy to prod until those are corrected.
