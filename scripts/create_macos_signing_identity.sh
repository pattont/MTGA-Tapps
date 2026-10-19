#!/usr/bin/env bash
# Create the stable, self-signed macOS code-signing identity for release builds.
#
# Run ONCE by the maintainer, then keep the .p12 and its password offline as a
# backup. Every release is signed with this one certificate (CI imports it and
# exports MACOS_SIGN_IDENTITY for scripts/build_macos_app.sh), so the app's
# designated requirement becomes
#   identifier "com.travispatton.mtgatracker" and certificate root = H"..."
# instead of an ad-hoc cdhash that changes on every build. That keeps macOS
# privacy (TCC) grants such as Automation across in-app updates.
#
# A self-signed certificate is NOT trusted by Gatekeeper: first-install UX is
# unchanged from ad-hoc signing (right-click Open / "Open Anyway"). It is not
# a substitute for an Apple Developer ID and must not be notarized.
#
# Do not regenerate it for later releases: a new certificate changes the
# designated requirement once, and users re-grant TCC permissions after that
# update. Losing it costs exactly that, nothing more.
#
# Usage: scripts/create_macos_signing_identity.sh [output-dir]
#   output-dir defaults to ~/.config/tapps-tracker (never inside the repo).
#   OPENSSL selects the openssl binary (OpenSSL 3+ or LibreSSL both work).
#   MACOS_SIGNING_P12_PASSWORD supplies the export password; otherwise a
#   random one is generated and written next to the .p12 (mode 0600).
set -euo pipefail

CN="Tapps Tracker Code Signing"
OPENSSL="${OPENSSL:-openssl}"
OUT_DIR="${1:-$HOME/.config/tapps-tracker}"
STEM="tapps-tracker-codesign"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
case "$OUT_DIR/" in
  "$ROOT_DIR"/*)
    echo "Refusing to write signing material inside the repository ($OUT_DIR)." >&2
    exit 2
    ;;
esac
P12="$OUT_DIR/$STEM.p12"
CRT="$OUT_DIR/$STEM.crt"
PW_FILE="$OUT_DIR/$STEM.p12.password"

for existing in "$P12" "$CRT" "$PW_FILE"; do
  if [[ -e "$existing" ]]; then
    echo "$existing already exists. Releases must keep using ONE identity;" >&2
    echo "delete it yourself only if you really mean to replace it." >&2
    exit 1
  fi
done

umask 077
WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

cat > "$WORK/req.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no

[dn]
CN = $CN

[ext]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
subjectKeyIdentifier = hash
EOF

# RSA 2048 + SHA-256: the combination codesign and every macOS release accept.
"$OPENSSL" req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
  -config "$WORK/req.cnf" -keyout "$WORK/key.pem" -out "$WORK/cert.pem" 2>/dev/null

if [[ -n "${MACOS_SIGNING_P12_PASSWORD:-}" ]]; then
  printf '%s' "$MACOS_SIGNING_P12_PASSWORD" > "$WORK/pw"
else
  # URL-safe characters only, so it pastes cleanly anywhere.
  "$OPENSSL" rand -base64 33 | tr -d '\n' | tr '+/' '-_' > "$WORK/pw"
fi

# SHA1-3DES bags + SHA-1 MAC: `security import` on macOS cannot read the
# AES/PBKDF2 PKCS#12 that OpenSSL 3 writes by default.
"$OPENSSL" pkcs12 -export -name "$CN" \
  -inkey "$WORK/key.pem" -in "$WORK/cert.pem" \
  -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 \
  -passout "file:$WORK/pw" -out "$WORK/identity.p12"

# Round-trip check: the archive opens with the password and holds the key.
"$OPENSSL" pkcs12 -in "$WORK/identity.p12" -passin "file:$WORK/pw" -nocerts -nodes \
  2>/dev/null | grep -q "PRIVATE KEY" || { echo "PKCS#12 round-trip failed" >&2; exit 1; }

mv "$WORK/identity.p12" "$P12"
mv "$WORK/cert.pem" "$CRT"
if [[ -z "${MACOS_SIGNING_P12_PASSWORD:-}" ]]; then
  mv "$WORK/pw" "$PW_FILE"
fi
chmod 600 "$P12"
chmod 644 "$CRT"
# The unencrypted key.pem is deleted with $WORK; the .p12 is the only copy.

SHA1="$("$OPENSSL" x509 -in "$CRT" -noout -fingerprint -sha1 | sed 's/.*=//; s/://g')"
ENDDATE="$("$OPENSSL" x509 -in "$CRT" -noout -enddate | sed 's/.*=//')"

cat <<EOF

Created the code-signing identity "$CN"
  PKCS#12 (key + certificate): $P12
  Certificate (public):        $CRT
EOF
if [[ -z "${MACOS_SIGNING_P12_PASSWORD:-}" ]]; then
  echo "  Export password:             $PW_FILE"
fi
cat <<EOF
  SHA-1 (codesign identity):   $SHA1
  Valid until:                 $ENDDATE

Store it as GitHub Actions secrets (values never appear on screen):

  base64 -i "$P12" | gh secret set MACOS_SIGNING_P12 -R pattont/MTGA-Tapps
EOF
if [[ -z "${MACOS_SIGNING_P12_PASSWORD:-}" ]]; then
  echo "  gh secret set MACOS_SIGNING_P12_PASSWORD -R pattont/MTGA-Tapps < \"$PW_FILE\""
else
  echo "  printf '%s' \"\$MACOS_SIGNING_P12_PASSWORD\" | gh secret set MACOS_SIGNING_P12_PASSWORD -R pattont/MTGA-Tapps"
fi
cat <<EOF
  gh secret list -R pattont/MTGA-Tapps

Then back up the .p12 and its password offline (password manager), and keep
them out of the repository. The release workflow imports the identity into a
temporary keychain and signs with it; without the secrets it falls back to
ad-hoc signing. For a local signed build, import the .p12 into a keychain and
run: MACOS_SIGN_IDENTITY=$SHA1 scripts/build_macos_app.sh
EOF
