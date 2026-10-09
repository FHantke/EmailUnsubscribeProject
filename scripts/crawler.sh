# Defines the crawler command for this shell session:  source scripts/crawler.sh
# Works in bash and zsh

# Absolute project root, from this file's location (bash sets BASH_SOURCE, zsh sets $0)
_crawler_src="${BASH_SOURCE[0]:-$0}"
CRAWLER_PROJECT_ROOT="$(cd "$(dirname "$_crawler_src")/.." && pwd)"
unset _crawler_src

crawler() {
  local testrun="$CRAWLER_PROJECT_ROOT/testrun"
  # Each call starts a fresh run.log; tee -i keeps it alive on Ctrl+C so the last lines are saved
  docker run --rm -it --platform linux/amd64 --shm-size=2g \
    --env-file "$testrun/crawler.env" \
    -v "$testrun:/data" --init \
    enfbots-crawler:local "$@" 2>&1 | tee -i "$testrun/run.log"
}
