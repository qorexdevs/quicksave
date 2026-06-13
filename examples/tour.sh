#!/usr/bin/env bash
# A 30-second tour: an agent wipes files git never tracked, quicksave brings them back.
# Run it anywhere - it works in a throwaway temp dir and cleans up after itself.
set -e

dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cd "$dir"

mkdir -p src
printf 'def main():\n    print("hi")\n' > src/app.py
printf 'API_KEY=secret\n' > .env          # untracked by git on purpose
printf '# my project\n' > README.md

quicksave init
quicksave save -n pre-agent -m "before the agent runs"

echo
echo '$ rm -rf src .env        # the agent wipes files git never tracked'
rm -rf src .env
echo '$ ls -A'
ls -A

echo
echo '$ quicksave restore pre-agent --clean'
quicksave restore pre-agent --clean
echo '$ ls -A && cat src/app.py'
ls -A
cat src/app.py
