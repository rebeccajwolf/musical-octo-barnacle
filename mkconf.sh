#!/bin/bash

# Makes accounts.json

cat > /app/accounts.json <<EOF
${ACCOUNTS}
EOF


# Makes config.yaml
cat > /app/config-private.yaml <<EOF
# config-private.yaml
apprise:
  urls:
    - "${TOKEN}" # Replace with your actual Apprise service URLs
EOF
