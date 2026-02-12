.PHONY: all
all:

.PHONY: test
test: checkstyle test-unit

# for now no tests anymore in test/ after retry moved to github.com/okurz/retry
.PHONY: test-unit
test-unit: test-more-bash test-python
	prove -r test/

test-more-bash:
	git clone https://github.com/ingydotnet/test-more-bash.git --depth 1 -b 0.0.5

.PHONY: test-python
test-python:
	py.test test

.PHONY: checkstyle
checkstyle: test-shellcheck checkstyle-python

.PHONY: test-shellcheck
test-shellcheck:
	@which shellcheck >/dev/null 2>&1 || echo "Command 'shellcheck' not found, can not execute shell script checks"
	# many files report errors so far hence only including a fixed list so far
	#shellcheck -x $$(file --mime-type * | sed -n 's/^\(.*\):.*text\/x-shellscript.*$$/\1/p')
	shellcheck -x hosts-yaml-to-aaaa

.PHONY: checkstyle-python
checkstyle-python:
	@which ruff >/dev/null 2>&1 || echo "Command 'ruff' not found, can not execute python style checks"
	ruff check
