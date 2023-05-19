#!/usr/bin/env bash

set -e
dir=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd)

TEST_MORE_PATH=$dir/../test-more-bash
BASHLIB="`
    find $TEST_MORE_PATH -type d |
    grep -E '/(bin|lib)$' |
    xargs -n1 printf "%s:"`"
PATH=$BASHLIB$PATH

source bash+ :std
use Test::More
plan tests 6

call_cmd() {
    $dir/../count_fail_ratio $*
}

rc=0
output=$(runs=3 call_cmd true 2>&1) || rc=$?
is "$rc" 0 'successful run for no fails'
like "$output" 'Run: 3. Fails: 0. Fail ratio 0%. No fails, computed failure probability < 100.00%' 'counted all successes'

rc=0
output=$(runs=30 call_cmd true 2>&1) || rc=$?
is "$rc" 0 'successful run for many no fails'
like "$output" 'Run: 30. Fails: 0. Fail ratio 0%.*< 10.00%' 'computed failure probability lowers to < 10% for enough runs'

rc=0
output=$(runs=3 call_cmd false 2>&1) || rc=$?
is "$rc" 0 'successful run for all fails'
like "$output" 'count_fail_ratio: Run: 3. Fails: 3. Fail ratio 100.00%' 'counted all fails'
