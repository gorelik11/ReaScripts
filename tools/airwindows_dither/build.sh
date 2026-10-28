#!/bin/sh
# Builds build/awproc-arm64 and build/awproc-x86_64 from the unmodified
# Airwindows sources in vendor/, plus the verification hosts in oracle/.
# -ffp-contract=off: no fused multiply-add, so the arithmetic is the plain
# IEEE sequence the source spells out. Ditherbox2018 goes only into the
# x86_64 build: its long double is 80-bit x87 there, as in the original
# Intel binary, but plain double on arm64. It also needs -fwrapv (its noise
# generators overflow int, which the 2008-era gcc wrapped) and
# shim/legacy_math.h (that gcc had no long double math overloads).
set -e
cd "$(dirname "$0")"
CXX="${CXX:-clang++}"
for arch in arm64 x86_64; do
	out=build/$arch
	mkdir -p $out
	plugins="Dark Ditherbox Monitoring TPDFWide NotJustAnotherDither SpatializeDither VinylDither TapeDither StudioTan DarkStereo"
	defs=""
	if [ $arch = x86_64 ]; then plugins="$plugins Ditherbox2018"; defs="-DAW_WITH_2018"; fi
	FLAGS="-arch $arch -O2 -ffp-contract=off -fno-fast-math -std=c++11 -w -Ishim"
	for p in $plugins; do
		extra=""
		[ $p = Ditherbox2018 ] && extra="-fwrapv -include legacy_math.h"
		"$CXX" $FLAGS -Ivendor/$p -Iderived/$p -DAW_PLUGIN=$p $extra -c aw_plugin_tu.cpp -o $out/$p.o
	done
	"$CXX" $FLAGS $defs -c awproc.cpp -o $out/awproc.o
	"$CXX" -arch $arch -o build/awproc-$arch $out/*.o
	cc -arch $arch -O2 -o build/vst2_oracle-$arch oracle/vst2_oracle.c
done
echo "built build/awproc-{arm64,x86_64} build/vst2_oracle-{arm64,x86_64}"
