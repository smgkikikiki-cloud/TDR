# Market-activity routing of the M7.0 CREATE candidates (routing only)

> Separate step before current-market Bootstrap activation. It does not change any CREATE / REVIEW / HOLD outcome and does not say whether an identity exists; `INACTIVE_INFERRED` identities keep their canonical identity and are routed to a historical/inactive lane. Parameters are proposals (`market_activity/policy.yaml`).

- Package months: 2564-01 … 2569-09 (69). **Explicit zero rows in the package: 0** — a zero month only ever appears as a missing row, so no true zero can be established until Ice's `ABSENT_IS_ZERO` is confirmed.
- CREATE candidates classified: **67**.

## Result
**Actual (authoritative): Ice absent-row semantics UNKNOWN (Q-ICE-ABSENT-ROW open): a missing row is never a zero** — states {'UNKNOWN': 60, 'ACTIVE': 6, 'DECLINING': 1}; lanes {'ACTIVITY_UNCLASSIFIED': 60, 'CURRENT_DISCOVERY': 7}.

**What-if (non-authoritative): NOT AUTHORITATIVE: assumes every missing row in 2564-01..2569-09 is a guaranteed zero** — states {'DECLINING': 8, 'ACTIVE': 6, 'UNKNOWN': 31, 'INACTIVE_INFERRED': 22}; lanes {'CURRENT_DISCOVERY': 14, 'ACTIVITY_UNCLASSIFIED': 31, 'HISTORICAL_INACTIVE': 22}.

## Representative dormant models — monthly registrations, last 24 months (`·` = no row)

| Group | 67-10 | 67-11 | 67-12 | 68-01 | 68-02 | 68-03 | 68-04 | 68-05 | 68-06 | 68-07 | 68-08 | 68-09 | 68-10 | 68-11 | 68-12 | 69-01 | 69-02 | 69-03 | 69-04 | 69-05 | 69-06 | 69-07 | 69-08 | 69-09 | Actual | What-if |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| toyota-toyota-sienta | · | · | · | · | · | 1 | · | 2 | 2 | · | 2 | · | 1 | · | · | · | · | · | 3 | 1 | · | · | 1 | · | UNKNOWN | INACTIVE_INFERRED |
| honda-jazz | 1 | 2 | 4 | · | 1 | 2 | · | 1 | 1 | · | 1 | · | · | 1 | · | · | · | 1 | · | 1 | 1 | · | 1 | · | UNKNOWN | DECLINING |
| toyota-vios | 2 | · | · | · | 2 | · | · | · | 2 | 7 | 14 | · | 6 | 1 | · | · | · | · | · | 1 | · | · | · | · | UNKNOWN | INACTIVE_INFERRED |
| nissan-note | · | · | · | · | 1 | · | · | · | · | · | · | · | · | · | 1 | · | · | · | · | · | · | · | 1 | · | UNKNOWN | INACTIVE_INFERRED |
| nissan-nissan-march | · | · | · | · | 1 | · | · | 1 | · | · | · | · | · | · | · | · | · | · | · | · | 1 | · | 1 | · | UNKNOWN | INACTIVE_INFERRED |

Why: toyota-toyota-sienta: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold; honda-jazz: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold; toyota-vios: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold; nissan-note: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold; nissan-nissan-march: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold

## Per CREATE candidate

| Group | Actual | What-if | Last inferred-inactive spell began (what-if) |
|---|---|---|---|
| bentley-bentley-continental | UNKNOWN | DECLINING |  |
| bmw-bmw-m2 | ACTIVE | ACTIVE | 2566-01 |
| bmw-bmw-m3 | ACTIVE | ACTIVE |  |
| bmw-bmw-m4 | ACTIVE | ACTIVE |  |
| bmw-bmw-m5 | UNKNOWN | UNKNOWN |  |
| chevrolet-chevrolet-corvette | UNKNOWN | DECLINING |  |
| chevrolet-trailblazer | UNKNOWN | INACTIVE_INFERRED | 2566-06 |
| daihatsu-daihatsu-copen | UNKNOWN | UNKNOWN |  |
| daihatsu-daihatsu-move | UNKNOWN | DECLINING |  |
| ferrari-ferrari-488 | UNKNOWN | INACTIVE_INFERRED | 2566-08 |
| ferrari-ferrari-portofino | UNKNOWN | UNKNOWN |  |
| ferrari-ferrari-purosangue | UNKNOWN | UNKNOWN |  |
| ford-ford-focus | UNKNOWN | UNKNOWN |  |
| foton-bj1041 | UNKNOWN | INACTIVE_INFERRED | 2566-06 |
| foton-eview | ACTIVE | ACTIVE |  |
| honda-brio | UNKNOWN | INACTIVE_INFERRED | 2568-01 |
| honda-honda-acty | UNKNOWN | UNKNOWN |  |
| honda-honda-amaze | UNKNOWN | UNKNOWN |  |
| honda-honda-fit | UNKNOWN | UNKNOWN |  |
| honda-honda-freed | UNKNOWN | UNKNOWN |  |
| honda-honda-n-box | DECLINING | INACTIVE_INFERRED | 2566-10 |
| honda-honda-stepwagon | UNKNOWN | INACTIVE_INFERRED | 2566-10 |
| honda-jazz | UNKNOWN | DECLINING |  |
| honda-prelude | UNKNOWN | UNKNOWN |  |
| honda-super-one | UNKNOWN | UNKNOWN |  |
| hyundai-genesis-g80 | UNKNOWN | UNKNOWN |  |
| hyundai-kona | UNKNOWN | UNKNOWN |  |
| hyundai-tucson | UNKNOWN | UNKNOWN |  |
| jac-t8 | UNKNOWN | INACTIVE_INFERRED | 2568-02 |
| jaecoo-jaecoo-j6 | ACTIVE | ACTIVE |  |
| jeep-jeep-gladiator | UNKNOWN | INACTIVE_INFERRED | 2567-09 |
| kia-k2500 | UNKNOWN | INACTIVE_INFERRED | 2565-09 |
| lamborghini-lamborghini-temerario | UNKNOWN | UNKNOWN |  |
| land-rover-land-rover-discovery | UNKNOWN | UNKNOWN |  |
| lexus-lexus-rc | UNKNOWN | UNKNOWN |  |
| lotus-emira | UNKNOWN | UNKNOWN |  |
| maserati-maserati-ghibli | UNKNOWN | INACTIVE_INFERRED | 2566-02 |
| maserati-maserati-mc20 | UNKNOWN | UNKNOWN |  |
| maserati-maserati-quattroporte | UNKNOWN | UNKNOWN |  |
| mclaren-mclaren-artura | UNKNOWN | UNKNOWN |  |
| nissan-leaf | UNKNOWN | INACTIVE_INFERRED | 2566-10 |
| nissan-nissan-fairlady | UNKNOWN | DECLINING |  |
| nissan-nissan-march | UNKNOWN | INACTIVE_INFERRED | 2567-04 |
| nissan-note | UNKNOWN | INACTIVE_INFERRED | 2567-02 |
| nissan-urvan | UNKNOWN | INACTIVE_INFERRED | 2567-05 |
| peugeot-peugeot-408 | UNKNOWN | INACTIVE_INFERRED | 2569-04 |
| rolls-royce-rolls-royce-cullinan | UNKNOWN | INACTIVE_INFERRED | 2567-09 |
| rolls-royce-rolls-royce-phantom | UNKNOWN | UNKNOWN |  |
| rolls-royce-rolls-royce-spectre | UNKNOWN | UNKNOWN |  |
| seres-seres-ec31 | UNKNOWN | INACTIVE_INFERRED | 2568-05 |
| sokon-crc50 | UNKNOWN | INACTIVE_INFERRED | 2566-03 |
| subaru-subaru-wrx | UNKNOWN | DECLINING |  |
| suzuki-apv | UNKNOWN | UNKNOWN |  |
| suzuki-grand-vitara | UNKNOWN | UNKNOWN |  |
| suzuki-suzuki-spacia | UNKNOWN | DECLINING |  |
| tata-tata-xenon | UNKNOWN | INACTIVE_INFERRED | 2566-01 |
| toyota-toyota-roomy | UNKNOWN | UNKNOWN |  |
| toyota-toyota-sienta | UNKNOWN | INACTIVE_INFERRED | 2567-08 |
| toyota-toyota-tr | UNKNOWN | INACTIVE_INFERRED | 2569-05 |
| toyota-vios | UNKNOWN | INACTIVE_INFERRED | 2567-01 |
| volkswagen-volkswagen-caddy | UNKNOWN | UNKNOWN |  |
| volkswagen-volkswagen-golf | UNKNOWN | UNKNOWN |  |
| volkswagen-volkswagen-touareg | UNKNOWN | UNKNOWN |  |
| volkswagen-vw-tiguan | UNKNOWN | UNKNOWN |  |
| volt-volt-volt | UNKNOWN | DECLINING |  |
| wuling-e10 | UNKNOWN | UNKNOWN |  |
| zeekr-zeekr-7x | ACTIVE | ACTIVE |  |
