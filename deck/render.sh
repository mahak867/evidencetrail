set -e
S=${PPTX_SKILL:?set PPTX_SKILL to the pptx skill folder}
python3 build_deck.py >/dev/null
python3 $S/scripts/office/soffice.py --headless --convert-to pdf EvidenceTrail_CODERED26_Round1.pptx >/dev/null 2>&1
rm -f slide-*.jpg; pdftoppm -jpeg -r ${R:-50} EvidenceTrail_CODERED26_Round1.pdf slide
