# Market-activity routing of the M7.0 CREATE candidates (routing only)

> Separate step before current-market Bootstrap activation. It does not change any CREATE / REVIEW / HOLD outcome and does not say whether an identity exists; `INACTIVE_INFERRED` identities keep their canonical identity and are routed to a historical/inactive lane. Parameters are proposals (`market_activity/policy.yaml`).

- Package months: 2564-01 … 2569-09 (69). **Explicit zero rows in the package: 0** — a zero month only ever appears as a missing row, so no true zero can be established until Ice's `ABSENT_IS_ZERO` is confirmed.
- CREATE candidates classified: **82**.

## Result
**Actual (authoritative): Ice absent-row semantics UNKNOWN (Q-ICE-ABSENT-ROW open): a missing row is never a zero** — states {'UNKNOWN': 70, 'ACTIVE': 9, 'DECLINING': 3}; lanes {'ACTIVITY_UNCLASSIFIED': 70, 'CURRENT_DISCOVERY': 12}.

**What-if (non-authoritative): NOT AUTHORITATIVE: assumes every missing row in 2564-01..2569-09 is a guaranteed zero** — states {'UNKNOWN': 38, 'DECLINING': 10, 'ACTIVE': 9, 'INACTIVE_INFERRED': 25}; lanes {'ACTIVITY_UNCLASSIFIED': 38, 'CURRENT_DISCOVERY': 19, 'HISTORICAL_INACTIVE': 25}.

## Representative dormant models — monthly registrations, last 24 months (`·` = no row)

| Group | 67-10 | 67-11 | 67-12 | 68-01 | 68-02 | 68-03 | 68-04 | 68-05 | 68-06 | 68-07 | 68-08 | 68-09 | 68-10 | 68-11 | 68-12 | 69-01 | 69-02 | 69-03 | 69-04 | 69-05 | 69-06 | 69-07 | 69-08 | 69-09 | Actual | What-if |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| toyota-toyota-sienta | · | · | · | · | · | 1 | · | 2 | 2 | · | 2 | · | 1 | · | · | · | · | · | 3 | 1 | · | · | 1 | · | UNKNOWN | INACTIVE_INFERRED |
| honda-jazz | 1 | 2 | 4 | · | 1 | 2 | · | 1 | 1 | · | 1 | · | · | 1 | · | · | · | 1 | · | 1 | 1 | · | 1 | · | not a CREATE | not a CREATE |
| toyota-vios | 2 | · | · | · | 2 | · | · | · | 2 | 7 | 14 | · | 6 | 1 | · | · | · | · | · | 1 | · | · | · | · | UNKNOWN | INACTIVE_INFERRED |
| nissan-note | · | · | · | · | 1 | · | · | · | · | · | · | · | · | · | 1 | · | · | · | · | · | · | · | 1 | · | UNKNOWN | INACTIVE_INFERRED |
| nissan-nissan-march | · | · | · | · | 1 | · | · | 1 | · | · | · | · | · | · | · | · | · | · | · | · | 1 | · | 1 | · | UNKNOWN | INACTIVE_INFERRED |

Why: toyota-toyota-sienta: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold; toyota-vios: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold; nissan-note: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold; nissan-nissan-march: ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold

## Per CREATE candidate

| Group | Actual | What-if | Last inferred-inactive spell began (what-if) |
|---|---|---|---|
| audi-audi-a8l | UNKNOWN | UNKNOWN |  |
| audi-audi-s3 | UNKNOWN | UNKNOWN |  |
| bentley-bentley-continental | UNKNOWN | DECLINING |  |
| bmw-bmw-m2 | ACTIVE | ACTIVE | 2566-01 |
| bmw-bmw-m3 | ACTIVE | ACTIVE |  |
| bmw-bmw-m4 | ACTIVE | ACTIVE |  |
| bmw-bmw-m5 | UNKNOWN | UNKNOWN |  |
| bmw-x2 | UNKNOWN | INACTIVE_INFERRED | 2566-09 |
| byd-e6 | UNKNOWN | INACTIVE_INFERRED | 2569-02 |
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
| honda-honda-freed | UNKNOWN | UNKNOWN |  |
| honda-honda-n-box | DECLINING | INACTIVE_INFERRED | 2566-10 |
| honda-prelude | UNKNOWN | UNKNOWN |  |
| honda-super-one | UNKNOWN | UNKNOWN |  |
| hyundai-genesis-g80 | UNKNOWN | UNKNOWN |  |
| hyundai-kona | UNKNOWN | UNKNOWN |  |
| hyundai-tucson | UNKNOWN | UNKNOWN |  |
| isuzu-isuzu-cab4 | UNKNOWN | UNKNOWN |  |
| jac-t8 | UNKNOWN | INACTIVE_INFERRED | 2568-02 |
| jaecoo-jaecoo-j5 | ACTIVE | ACTIVE |  |
| jaecoo-jaecoo-j6 | ACTIVE | ACTIVE |  |
| jaecoo-jaecoo-j7 | DECLINING | DECLINING |  |
| jeep-jeep-gladiator | UNKNOWN | INACTIVE_INFERRED | 2567-09 |
| kia-k2500 | UNKNOWN | INACTIVE_INFERRED | 2565-09 |
| lamborghini-lamborghini-temerario | UNKNOWN | UNKNOWN |  |
| land-rover-land-rover-discovery | UNKNOWN | UNKNOWN |  |
| lexus-lexus-rc | UNKNOWN | UNKNOWN |  |
| lotus-emira | UNKNOWN | UNKNOWN |  |
| maserati-maserati-ghibli | UNKNOWN | INACTIVE_INFERRED | 2566-02 |
| maserati-maserati-mc20 | UNKNOWN | UNKNOWN |  |
| maserati-maserati-quattroporte | UNKNOWN | UNKNOWN |  |
| maxus-maxus-v80 | UNKNOWN | INACTIVE_INFERRED | 2565-09 |
| mazda-mazda-mx-30 | UNKNOWN | UNKNOWN |  |
| mazda-mazda6e | ACTIVE | ACTIVE |  |
| mclaren-mclaren-artura | UNKNOWN | UNKNOWN |  |
| nissan-leaf | UNKNOWN | INACTIVE_INFERRED | 2566-10 |
| nissan-nissan-be-1 | UNKNOWN | UNKNOWN |  |
| nissan-nissan-fairlady | UNKNOWN | DECLINING |  |
| nissan-nissan-march | UNKNOWN | INACTIVE_INFERRED | 2567-04 |
| nissan-note | UNKNOWN | INACTIVE_INFERRED | 2567-02 |
| nissan-urvan | UNKNOWN | INACTIVE_INFERRED | 2567-05 |
| peugeot-peugeot-408 | UNKNOWN | INACTIVE_INFERRED | 2569-04 |
| peugeot-peugeot-5008 | UNKNOWN | INACTIVE_INFERRED | 2568-08 |
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
| volkswagen-volkswagen-multivan | UNKNOWN | UNKNOWN |  |
| volkswagen-volkswagen-t-roc | UNKNOWN | UNKNOWN |  |
| volkswagen-volkswagen-touareg | UNKNOWN | UNKNOWN |  |
| volkswagen-vw-idbuzz | UNKNOWN | DECLINING |  |
| volkswagen-vw-t-cross | UNKNOWN | UNKNOWN |  |
| volkswagen-vw-tiguan | UNKNOWN | UNKNOWN |  |
| volt-volt-volt | UNKNOWN | DECLINING |  |
| volvo-volvo-es90 | ACTIVE | ACTIVE |  |
| wuling-binguo | DECLINING | DECLINING |  |
| wuling-e10 | UNKNOWN | UNKNOWN |  |
| zeekr-zeekr-7x | ACTIVE | ACTIVE |  |
