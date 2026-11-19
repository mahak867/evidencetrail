"""CLI: python et.py inject payment error | python et.py clear | python et.py investigate "alert text"."""
import json
import sys

from evidencetrail import faults
from evidencetrail.investigator import investigate

cmd = sys.argv[1]
if cmd == "inject":
    extra = dict(a.split("=", 1) for a in sys.argv[4:])
    faults.inject(sys.argv[2], sys.argv[3], **extra)
    print("injected", sys.argv[2:])
elif cmd == "clear":
    faults.clear_all(); print("cleared")
elif cmd == "investigate":
    print(json.dumps(investigate(sys.argv[2]), indent=2, default=str))
