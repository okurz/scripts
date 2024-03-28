.PHONY: all
all:

.PHONY: test
test: checkstyle test-unit

.PHONY: test-unit
test-unit: test-more-bash
	prove -r test/

test-more-bash:
	git clone https://github.com/ingydotnet/test-more-bash.git --depth 1 -b 0.0.5

.PHONY: checkstyle
checkstyle: test-shellcheck

.PHONY: test-shellcheck
test-shellcheck:
	@which shellcheck >/dev/null 2>&1 || echo "Command 'shellcheck' not found, can not execute shell script checks"
	# many files report errors so far hence only including a fixed list so far
	#shellcheck -x $$(file --mime-type * | sed -n 's/^\(.*\):.*text\/x-shellscript.*$$/\1/p')
	shellcheck -x count-fail-ratio
