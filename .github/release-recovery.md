Canonical vehicle release recovery

The release workflow stages the exact validated `vehicle-release.json` on the temporary `release-staging` branch before deployment preflight. The staged payload contains no credentials. It exists so an authorized database-management connection can verify and activate the exact CI-built release when the Actions deployment credential is unavailable; after recovery, the branch should be reset away from the staged payload.
