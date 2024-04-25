#!/usr/bin/env bash

for x in "$@"
do
    echo "hooked: $x"
done
exit 1
