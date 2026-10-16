#!/usr/bin/env python3
"""Create YOUR OWN licence signing key pair (do this once, before you sell).

  pip install cryptography
  python tools/make_keys.py

It writes:
  private_key.pem              keep SECRET. Never put it in the installer, a ZIP you share, or GitHub.
  private_key_one_line.txt     the same key on one line, to paste into Apps Script > Project Settings > Script properties > PRIVATE_KEY
and patches the PUBLIC key into school_system.py (LIC_N), so only codes signed with your key are accepted.
Rebuild the installers after running it.
"""
import os, re, sys
try:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
except ImportError:
    sys.exit('Run:  pip install cryptography   then run this again.')
here = os.path.dirname(os.path.abspath(__file__))
target = os.path.join(here, '..', 'school_system.py')
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
n = key.public_key().public_numbers().n
open(os.path.join(here, '..', 'private_key.pem'), 'w').write(pem)
open(os.path.join(here, '..', 'private_key_one_line.txt'), 'w').write(pem.strip().replace('\n', '\\n'))
src = open(target, encoding='utf-8').read()
new, cnt = re.subn(r"LIC_N = int\('[0-9a-fA-F]+', 16\)", "LIC_N = int('%x', 16)" % n, src)
if cnt != 1:
    sys.exit('Could not find LIC_N in school_system.py')
open(target, 'w', encoding='utf-8').write(new)
print('Done. New public key written into school_system.py. Keep private_key.pem secret and paste private_key_one_line.txt into Apps Script.')
