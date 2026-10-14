"""TDR Identity Resolution — a provider-agnostic subsystem that decides how an external vehicle
identity (e.g. an Ice ``model_group``) relates to a TDR canonical entity.

STATUS: Contract v1 is a DRAFT for owner review (see ``README.md`` and ``contract/v1/SPEC.md``). This
package currently holds the versioned contract, the golden corpus and the contract-level tooling only.
There is no resolver yet and nothing in production reads it; ``vehreg/ice_crosswalk.py`` and
``tools/ice_crosswalk_match.py`` remain the live (compatibility) matcher.
"""
