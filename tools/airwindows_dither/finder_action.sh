#!/bin/zsh
# Finder Quick Action "Airwindows Dither…": asks for the dither, bit depth and
# (for Ditherbox) type, then dithers the selected files next to themselves and
# verifies each against the installed plugin. Remembers the last choice.
# AW_DITHER / AW_BITS / AW_TYPE skip the dialogs (for testing).
HERE="${0:A:h}"
PY="${AW_PYTHON:-$HOME/.venvs/madmom/bin/python}"
LAST="$HERE/last_choice"
LOG="$HERE/last_run.log"

names=(Dark SpatializeDither TPDFWide NotJustAnotherDither VinylDither TapeDither
	"Monitoring (Out16/Out24)" StudioTan Ditherbox "Ditherbox 2018")
keys=(dark spatialize tpdfwide njad vinyl tape monitoring studiotan ditherbox ditherbox2018)
types=(NJAD TPDF Trunc Flat Paul DbPaul Tape HiGloss Vinyl Spatial Natural)

# pick <prompt> <default> <items...>  -> chosen item, or nothing on Cancel
pick() {
	osascript - "$@" <<'EOF'
on run argv
	set l to items 3 thru -1 of argv
	set d to item 2 of argv
	if l does not contain d then set d to item 1 of l
	set r to choose from list l with prompt (item 1 of argv) default items {d} with title "Airwindows Dither"
	if r is false then return ""
	return item 1 of r
end run
EOF
}

alert() {
	osascript -e 'on run argv' -e 'display alert "Airwindows Dither" message (item 1 of argv) as critical' \
		-e 'end run' "$1" >/dev/null
}

notify() {
	osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "Airwindows Dither"' \
		-e 'end run' "$1"
}

(( $# )) || { alert "No files selected."; exit 1; }
last=("${(@f)$(cat "$LAST" 2>/dev/null)}")

dither="$AW_DITHER"
if [[ -z $dither ]]; then
	name=$(pick "Dither:" "${last[1]:-Dark}" "${names[@]}")
	[[ -n $name ]] || exit 0
	dither=${keys[${names[(i)$name]}]}
fi
bits="$AW_BITS"
if [[ -z $bits ]]; then
	b=$(pick "Output bit depth:" "${last[2]:-24 bit}" "24 bit" "16 bit")
	[[ -n $b ]] || exit 0
	bits=${b%% *}
fi
dtype="$AW_TYPE"
if [[ $dither == ditherbox* && -z $dtype ]]; then
	dtype=$(pick "Ditherbox type:" "${last[3]:-NJAD}" "${types[@]}")
	[[ -n $dtype ]] || exit 0
fi
[[ -n $name ]] && print -l "$name" "$b" "${dtype:-${last[3]}}" > "$LAST"

args=(--dither "$dither" --bits "$bits" --verify)
[[ -n $dtype ]] && args+=(--type "$dtype")
"$PY" "$HERE/aw_dither.py" "$@" "${args[@]}" >"$LOG" 2>&1
rc=$?

ok=$(grep -c 'bit-identical to' "$LOG")
skipped=$(grep -c '^exists, skipped' "$LOG")
clipped=$(grep -c 'clipped at full scale' "$LOG")
summary="$dither${dtype:+ $dtype} ${bits} bit: $ok of $# done, bit-identical"
(( clipped )) && summary+=", $clipped with clipping"
(( skipped )) && summary+=", $skipped skipped (output exists)"
if (( rc != 0 && ok + skipped < $# )); then
	alert "$summary"$'\n\n'"$(tail -5 "$LOG")"
else
	notify "$summary"
fi
exit $rc
