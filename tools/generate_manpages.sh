#!/bin/bash
# Generate benchmarks/<name>/manpage.1, the man page of each benchmark's target,
# from the benchmark's own source tree (so it matches the version we build).
# Used by CarpetFuzz and ProphetFuzz, which derive option combinations from it.
#
# Usage: tools/generate_manpages.sh [benchmark ...]   (default: all of them)
#
# The source tree comes from the benchmark's coverage image if it exists
# (fbpp/benchmark:coverage_cts_default_<name>_0), otherwise from an image built
# here from the benchmark's builder.Dockerfile. Targets without a man page get
# one from their --help output with help2man.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)

# benchmark -> shell command printing the man page on stdout, run in its image.
declare -A MANPAGE=(
  [binutils_nm-new]='cat /binutils-2.47/binutils/doc/nm.1'
  [binutils_objdump]='cat /binutils-2.47/binutils/doc/objdump.1'
  # help2man-made: the options are listed under DESCRIPTION, but CarpetFuzz's
  # parser only reads sections named OPTIONS.
  [bison_bison]='sed "s/^\.SH DESCRIPTION/.SH OPTIONS/" /bison-3.8/doc/bison.1'
  [expat_xmlwf]='docbook /libexpat/expat/doc/xmlwf.xml xmlwf.1'
  [ffmpeg_ffmpeg]='cd /ffmpeg-4.7 && perl doc/texi2pod.pl -Dconfig-not-all=1 -Idoc doc/ffmpeg.texi /tmp/ffmpeg.pod >/dev/null && pod2man --section=1 --center=" " --release=" " --date=" " --name=FFMPEG /tmp/ffmpeg.pod'
  # BSD mdoc macros; CarpetFuzz's parser reads man(7) macros.
  [file_file]='needs mandoc && mandoc -T man /file/doc/file.1'
  [libpng_pngimage]=static  # no man page or --help; manpage.1 is written by hand from pngimage.c
  [libtiff_tiff2pdf]='needs python3-sphinx && sphinx-build -q -b man /libtiff/doc /tmp/man >&2 && cat /tmp/man/tiff2pdf.1'
  [libxml2_xmllint]='docbook /libxml2/doc/xmllint.xml xmllint.1'
  # Option names are set in constant width (\f(CR), which CarpetFuzz's parser
  # does not strip; use bold, as most man pages do.
  [pcre2_pcre2test]='sed "s/\\\\f(CR/\\\\fB/g" /pcre2/doc/man/pcre2test.1'
  [x264_x264]='needs help2man && help2man -N --help-option=--fullhelp /x264/x264'
  [xz_xz]='cat /xz-5.2.5/src/xz/xz.1'
)

# Helpers available to the commands above.
HELPERS='
needs() { apt-get update -qq >&2 && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" >&2; }
docbook() {  # docbook <refentry.xml> <generated page>
  needs xsltproc docbook-xsl docbook-xml && cd /tmp &&
  xsltproc --nonet /usr/share/xml/docbook/stylesheet/docbook-xsl/manpages/docbook.xsl "$1" >&2 &&
  cat "/tmp/$2"
}
'

source_image() {
  local b=$1 cov="fbpp/benchmark:coverage_cts_default_${b}_0"
  if [ -n "$(docker images -q "$cov")" ]; then echo "$cov"; return; fi
  local tmp; tmp=$(mktemp -d)
  cp -r "$ROOT/benchmarks/$b/." "$tmp/"
  sed -i 's/{{CT_CONFIGURATION}}//' "$tmp/build.sh"
  docker build -q -t "fbpp/manpage-src:$b" -f "$tmp/builder.Dockerfile" "$tmp" \
    --build-arg parent_image=fbpp/base --build-arg CC=clang --build-arg CXX=clang++ >&2
  rm -rf "$tmp"
  echo "fbpp/manpage-src:$b"
}

benchmarks=("$@")
[ ${#benchmarks[@]} -gt 0 ] || benchmarks=("${!MANPAGE[@]}")

for b in "${benchmarks[@]}"; do
  cmd=${MANPAGE[$b]:-}
  [ -n "$cmd" ] || { echo "[x] no man page recipe for $b" >&2; exit 1; }
  if [ "$cmd" = static ]; then echo "[=] $b: kept the hand-written manpage.1"; continue; fi
  img=$(source_image "$b")
  out="$ROOT/benchmarks/$b/manpage.1"
  if docker run --rm --entrypoint bash "$img" -c "$HELPERS $cmd" > "$out.tmp" && [ -s "$out.tmp" ]; then
    mv "$out.tmp" "$out"
    echo "[+] $b: $(wc -l < "$out") lines from $img"
  else
    rm -f "$out.tmp"
    echo "[x] $b: failed" >&2
    exit 1
  fi
done
