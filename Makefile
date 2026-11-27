ISOLATE ?= 1

ifeq ($(ISOLATE),1)
UNSHARE := unshare -r -n
else
UNSHARE :=
endif

# Override to use uv, e.g. PYTHON_RUN="uv run"
PYTHON_RUN ?=

PYTEST_XDIST := $(shell python3 -c "import xdist" 2>/dev/null && echo "-n auto" || echo "")

PY_FILES ?= $(shell git ls-files '*.py')
PY_SCRIPTS ?= gh-pr-triage gitea-review-cleanup github-all-prs mac-to-ipv6 obs-pr-repair \
	openqa-db_query_last_use_of_module osc-get-pr-status pr-sweep osc-list-all-unresolvables \
	osc-sync-deps osc-sync-leap redmine-fetcher review-bot-batch suse-qa-sle-etherpad-status \
	git-plans-dir git-worktree-audit
PY_ALL = $(PY_FILES) $(PY_SCRIPTS)

SHELL_SCRIPTS ?= container-sle-internal-repos fate-to-jira find_duplicates gh-as-bot \
	git-delete-no-content-branches git-hijack-commit git-hooks/post-checkout git-pr-last \
	git-push-review-and-submit-rebased git-rebase-all-branches git-review git-review-branch \
	git-stack-list git-upstream-base glab-as-bot hosts-yaml-to-aaaa openqa-client-record-manual-test \
	openqa-clone-set openqa-find-longest-running-test-modules openqa-get-qem-bot-blocking-jobs \
	openqa-tag-build openqa-trigger-mm openqa_client_o3 openqa_client_osd openqa_clone_job_o3 \
	openqa_clone_job_osd osc-list-unresolvables osc-list-unresolvables-per-pkg \
	osc-staging-link-all-missing-deps osc-submit-dependencies osc-submit-dependencies2 \
	reencode-video-kia-niro-sg2 valgrind_full vimeo-review-dl vm vm-nographic zp \
	zypper-log-to-git-log zypper-rm-orphaned zypper-rm-unneeded

.PHONY: help
help: ## Display this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: all
all: help

.PHONY: test-unit
test-unit: ## Run dynamic tests with coverage report
	$(UNSHARE) $(PYTHON_RUN) python3 -m pytest $(PYTEST_XDIST) --cov --cov-report=xml --cov-report=term-missing

.PHONY: test-unit-no-coverage
test-unit-no-coverage: ## Run dynamic tests without coverage analysis and without style checks
	$(UNSHARE) $(PYTHON_RUN) python3 -m pytest $(PYTEST_XDIST)

.PHONY: check-ruff
check-ruff: ## Run ruff linting and formatting checks over all tracked Python files
	$(PYTHON_RUN) ruff check $(PY_ALL)
	$(PYTHON_RUN) ruff format --check $(PY_ALL)

.PHONY: tidy
tidy: ## Format code and fix linting issues
	$(PYTHON_RUN) ruff format $(PY_ALL)
	$(PYTHON_RUN) ruff check --fix $(PY_ALL)

.PHONY: check-conventions
check-conventions: ## Check for banned coding patterns
	@if git grep -nE '^\s*@(unittest\.mock\.|mock\.)?patch' test/; then \
		echo "Error: @patch decorator detected. Avoid to prevent argument ordering bugs."; \
		echo "   Fix: Use the 'mocker' fixture (pytest-mock) or a 'with patch():' context manager."; \
		exit 1; \
	fi

.PHONY: check-code-health
check-code-health: ## Find dead code (vulture)
	@echo "Checking code health…"
	@$(PYTHON_RUN) vulture $(PY_ALL) --min-confidence 80

.PHONY: check-types-ty
check-types-ty: ## Run the ty type checker over all tracked Python files
	$(PYTHON_RUN) ty check $(PY_ALL)

.PHONY: check-types
check-types: check-types-ty

.PHONY: check-shell
check-shell: ## Run shellcheck over the whitelisted shell scripts
	shellcheck -x $(SHELL_SCRIPTS)

.PHONY: check-lock
check-lock: ## Verify uv.lock is in sync with pyproject.toml
	uv lock --check

# aggregate targets

.PHONY: checkstyle
checkstyle: ## Run fast style and static analysis checks
	@$(MAKE) -j check-ruff check-conventions check-shell check-lock

.PHONY: checkstyle-all
checkstyle-all: ## Run all style and static analysis checks
	@$(MAKE) -j checkstyle check-types check-code-health

.PHONY: check-coverage-scope
check-coverage-scope: ## Verify every tracked Python file is at 100% statement and branch coverage
	$(PYTHON_RUN) python3 test/coverage_scope.py

.PHONY: test
test: ## Run all tests with coverage analysis and all style checks
	@$(MAKE) -j test-unit checkstyle-all
	@$(MAKE) check-coverage-scope

.PHONY: test-no-coverage
test-no-coverage: ## Run all tests *without* coverage analysis (faster)
	@$(MAKE) -j test-unit-no-coverage checkstyle

.PHONY: setup-hooks
setup-hooks: ## Install pre-commit git hooks
	pre-commit install --install-hooks -t commit-msg -t pre-commit
