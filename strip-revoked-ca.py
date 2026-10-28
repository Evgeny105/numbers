#!/usr/bin/env python3
"""Downstream eMudhra distrust patch, applied at the end of image builds.

Keep existing allowed certificates; supplement bundles with official Ubuntu roots. Version numbers of certifi/packages
are deliberately not changed: this is a local trust patch, not a vendor upgrade.
"""
import hashlib
import pathlib
import re
import ssl

DENY = set('''7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d
f2edaaff3d9b701fb4d14c9f285f8c0bad90fc3bcc1fa07d47f4718edaba34a5
d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4
86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b'''.split())
PEM = re.compile(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', re.S)

def fingerprints(data):
    return {hashlib.sha256(ssl.PEM_cert_to_DER_cert(p.decode('ascii'))).hexdigest()
            for p in PEM.findall(data)}


def supplement(data, official):
    existing = fingerprints(data)
    assert not (fingerprints(official) & DENY), 'Unsafe supplement'
    extra = [p for p in PEM.findall(official)
             if not (fingerprints(p) & existing)]
    return data + (b'\n' + b'\n'.join(extra) + b'\n' if extra else b'')


def main():
    official = pathlib.Path(__file__).with_name("public-ca-20260816.pem").read_bytes()
    count = 0
    seen = set()
    for root in ['/etc/ssl', '/usr/share/ca-certificates', '/usr/local/share/ca-certificates',
                 '/usr/local/lib', '/app/.venv/lib']:
        for candidate in pathlib.Path(root).rglob('*'):
            if candidate.suffix not in ('.crt', '.pem') or not candidate.is_file():
                continue
            path = candidate.resolve()
            if path in seen:
                continue
            seen.add(path)
            original = path.read_bytes()
            def replace(match):
                der = ssl.PEM_cert_to_DER_cert(match[0].decode('ascii'))
                return b'' if hashlib.sha256(der).hexdigest() in DENY else match[0]
            clean = PEM.sub(replace, original)
            # Only multi-root bundles, never individual certificate files.
            if len(PEM.findall(clean)) > 1:
                clean = supplement(clean, official)
            if clean == original:
                continue
            if not PEM.search(clean):
                assert str(path).startswith('/usr/share/ca-certificates/'), path
                path.unlink()
            else:
                path.write_bytes(clean)
            count += 1
    print('Revoked CA patch: files changed:', count)

if __name__ == '__main__':
    main()
