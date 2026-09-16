// Exact required marketing-consent copy (must be optional, unchecked by
// default). Consent is auditable: stored as a boolean plus this version
// string plus the acceptance timestamp (see tdr_customer_profiles in
// migration_v32_access_policy_and_quotas.sql).
export const MARKETING_CONSENT_VERSION = "2026-09-tdr-market-updates-v1";
export const MARKETING_CONSENT_TEXT =
  "I would like to receive market updates, research insights, product news, and occasional promotional communications from Thailand Development Report by email.";
