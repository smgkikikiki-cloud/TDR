"""Fixture-only source acquisition with explicit registry, scope, and local CAS.

There is intentionally no HTTP client in this module. All transport responses
must be supplied as prerecorded fixtures to DeterministicFakeHTTPTransport.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import unquote, urlsplit

from .offline_runner import _document_scope_error, utc_day
from .replay import _valid_document
from .validation import validate_fixture, validate_policy

DISPOSITIONS={"FETCH_OK","UNCHANGED","PARTIAL","SOURCE_BROKEN","BLOCKED"}
HEX64=re.compile(r"^[a-f0-9]{64}$")


def _canonical(value: Any) -> str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_source_registry(registry: dict) -> None:
    if (not isinstance(registry,dict) or registry.get("schema_version")!="1.0"
            or registry.get("execution_mode")!="PRERECORDED_FIXTURE_ONLY"
            or registry.get("live_requests_enabled") is not False
            or registry.get("redirects_enabled") is not False
            or not isinstance(registry.get("sources"),list) or not registry["sources"]):
        raise ValueError("source registry must fail closed to prerecorded fixtures")
    seen=set()
    for source in registry["sources"]:
        required={"source_id","authority","market","host_allowlist","path_prefix_allowlist",
                  "allowed_methods","allowed_content_types","permission_status","permission_notes",
                  "content_license_policy","allowed_fixture_licenses","robots_policy","rate_limit","retry_policy"}
        if not isinstance(source,dict) or required-set(source):
            raise ValueError("source registry entry is incomplete")
        source_id=source["source_id"]
        if not isinstance(source_id,str) or not source_id or source_id in seen:
            raise ValueError("source registry IDs must be unique non-empty strings")
        seen.add(source_id)
        hosts=source["host_allowlist"]
        paths=source["path_prefix_allowlist"]
        if (not isinstance(hosts,list) or not hosts or any(not isinstance(h,str) or not h or "*" in h for h in hosts)
                or not isinstance(paths,list) or not paths or any(not isinstance(p,str) or not p.startswith("/") for p in paths)):
            raise ValueError("source registry requires exact hosts and absolute path prefixes")
        if (source["authority"] not in {"OFFICIAL","ADMIN","SECONDARY"}
                or source["market"] not in {"TH","OTHER"}
                or source["permission_status"] not in {"SYNTHETIC_FIXTURE_ONLY","OWNER_LICENSED_FIXTURE"}
                or not isinstance(source["permission_notes"],str) or not source["permission_notes"].strip()
                or not isinstance(source["content_license_policy"],str) or not source["content_license_policy"].strip()
                or not isinstance(source["robots_policy"],str) or not source["robots_policy"].strip()):
            raise ValueError("source authority, permission, license, and robots policy must be explicit")
        if source["allowed_methods"] != ["GET"]:
            raise ValueError("fixture source adapters support GET only")
        if not source["allowed_fixture_licenses"] or not set(source["allowed_fixture_licenses"]) <= {"SYNTHETIC","OWNER_LICENSED"}:
            raise ValueError("source fixture license allowlist is invalid")
        rl=source["rate_limit"]
        retry=source["retry_policy"]
        if (not isinstance(rl,dict) or type(rl.get("minimum_interval_seconds")) is not int
                or rl["minimum_interval_seconds"] < 0 or type(rl.get("maximum_requests_per_utc_day")) is not int
                or rl["maximum_requests_per_utc_day"] < 1 or type(rl.get("retry_after_cap_seconds")) is not int
                or rl["retry_after_cap_seconds"] < 1 or not isinstance(retry,dict)
                or type(retry.get("maximum_attempts")) is not int or retry["maximum_attempts"] < 1
                or type(retry.get("cooldown_seconds")) is not int or retry["cooldown_seconds"] < 1):
            raise ValueError("source rate and retry limits must be positive integers")


def load_source_registry(path: str | Path | None = None) -> dict:
    target=Path(path) if path else Path(__file__).parent/"contract"/"source_registry.json"
    registry=json.loads(target.read_text(encoding="utf-8"))
    validate_source_registry(registry)
    return registry


@dataclass(frozen=True)
class PrerecordedHTTPResponse:
    status_code: int
    headers: dict[str,str]
    body: bytes
    fixture_license: str
    robots_allowed: bool
    retry_after_seconds: int=0
    elapsed_seconds: int=0
    final_url: str | None=None


class DeterministicFakeHTTPTransport:
    """An exact-URL response tape. Unknown URLs never fall through to a network."""
    offline_only=True
    external_http_calls=0

    def __init__(self,responses: dict[str,list[PrerecordedHTTPResponse] | PrerecordedHTTPResponse]):
        self._responses={url:(value if isinstance(value,list) else [value]) for url,value in responses.items()}
        self._cursor:dict[str,int]={}
        self.calls:list[dict]=[]

    def get(self,url: str) -> PrerecordedHTTPResponse:
        self.calls.append({"method":"GET","url":url})
        tape=self._responses.get(url)
        if not tape:
            raise KeyError("NO_PRERECORDED_RESPONSE")
        i=self._cursor.get(url,0)
        response=tape[min(i,len(tape)-1)]
        self._cursor[url]=i+1
        return response

    @classmethod
    def from_manifest(cls,path: str | Path) -> "DeterministicFakeHTTPTransport":
        manifest_path=Path(path).resolve()
        raw=json.loads(manifest_path.read_text(encoding="utf-8"))
        if raw.get("schema_version")!="1.0" or not isinstance(raw.get("responses"),list):
            raise ValueError("prerecorded response manifest is invalid")
        responses={}
        for row in raw["responses"]:
            body_path=(manifest_path.parent/row["body_file"]).resolve()
            if manifest_path.parent.resolve() not in body_path.parents:
                raise ValueError("fixture body path escapes response manifest directory")
            response=PrerecordedHTTPResponse(int(row["status_code"]),dict(row.get("headers",{})),
                body_path.read_bytes(),row.get("fixture_license",""),row.get("robots_allowed") is True,
                int(row.get("retry_after_seconds",0)),int(row.get("elapsed_seconds",0)),row.get("final_url"))
            responses.setdefault(row["url"],[]).append(response)
        return cls(responses)


class ContentAddressedEvidenceStore:
    """Local CAS for response bytes and normalized evidence documents."""
    def __init__(self,root: str | Path):
        self.root=Path(root)
        self.blobs=self.root/"blobs"/"sha256"
        self.documents=self.root/"documents"/"sha256"
        self.root.mkdir(parents=True,exist_ok=True)
        self.blobs.mkdir(parents=True,exist_ok=True)
        self.documents.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/"acquisition.sqlite",isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS requests(
          idempotency_key TEXT PRIMARY KEY, request_fingerprint TEXT NOT NULL,
          source_id TEXT NOT NULL, url TEXT NOT NULL, status TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0, retry_at INTEGER, result_json TEXT NOT NULL DEFAULT '{}',
          updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY, requests INTEGER NOT NULL DEFAULT 0,
          elapsed_seconds INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS source_rate(source_id TEXT PRIMARY KEY,next_allowed_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence(content_sha256 TEXT PRIMARY KEY,body_sha256 TEXT NOT NULL,
          document_json TEXT NOT NULL,source_id TEXT NOT NULL,recorded_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence_versions(document_fingerprint TEXT PRIMARY KEY,
          content_sha256 TEXT NOT NULL,body_sha256 TEXT NOT NULL,document_json TEXT NOT NULL,
          source_id TEXT NOT NULL,recorded_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS evidence_versions_content ON evidence_versions(content_sha256);
        """)

    def close(self) -> None:
        self.db.close()

    def put_blob(self,data: bytes) -> tuple[str,bool]:
        digest=_sha(data)
        path=self.blobs/digest[:2]/digest
        path.parent.mkdir(parents=True,exist_ok=True)
        inserted=not path.exists()
        if path.exists() and _sha(path.read_bytes())!=digest:
            path.unlink(); inserted=True
        if inserted:
            temp=path.with_suffix(".tmp")
            temp.write_bytes(data)
            temp.replace(path)
        if _sha(path.read_bytes())!=digest:
            raise ValueError("content-addressed blob hash mismatch")
        return f"fixture://cas/sha256/{digest}",inserted

    def read_blob(self,reference: str) -> bytes:
        prefix="fixture://cas/sha256/"
        if not reference.startswith(prefix) or not HEX64.fullmatch(reference[len(prefix):]):
            raise ValueError("invalid content-addressed fixture reference")
        path=self.blobs/reference[len(prefix):][:2]/reference[len(prefix):]
        data=path.read_bytes()
        if _sha(data)!=reference[len(prefix):]:
            raise ValueError("content-addressed blob hash mismatch")
        return data

    def get_request(self,key: str) -> dict | None:
        row=self.db.execute("SELECT * FROM requests WHERE idempotency_key=?",(key,)).fetchone()
        if not row:return None
        value=dict(row); value["result"]=json.loads(value.pop("result_json")); return value

    def get_rate_limit(self,source_id: str) -> int:
        row=self.db.execute("SELECT next_allowed_at FROM source_rate WHERE source_id=?",(source_id,)).fetchone()
        return int(row["next_allowed_at"]) if row else 0

    def usage(self,day: str) -> dict:
        row=self.db.execute("SELECT * FROM usage WHERE day=?",(day,)).fetchone()
        return dict(row) if row else {"day":day,"requests":0,"elapsed_seconds":0}

    def persist_request(self,key: str,fingerprint: str,source_id: str,url: str,status: str,
                        attempts: int,retry_at: int | None,result: dict,now: int) -> None:
        self.db.execute("""INSERT INTO requests(idempotency_key,request_fingerprint,source_id,url,status,attempts,
          retry_at,result_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO UPDATE SET
          status=excluded.status,attempts=excluded.attempts,retry_at=excluded.retry_at,
          result_json=excluded.result_json,updated_at=excluded.updated_at""",
          (key,fingerprint,source_id,url,status,attempts,retry_at,_canonical(result),now))

    def record_call(self,source_id: str,now: int,elapsed: int) -> None:
        day=utc_day(now)
        self.db.execute("INSERT INTO usage(day,requests,elapsed_seconds) VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET "+
            "requests=requests+excluded.requests,elapsed_seconds=elapsed_seconds+excluded.elapsed_seconds",
            (day,1,elapsed))
        self.db.execute("INSERT INTO source_rate(source_id,next_allowed_at) VALUES(?,?) ON CONFLICT(source_id) DO UPDATE SET "+
            "next_allowed_at=excluded.next_allowed_at",(source_id,now))

    def set_rate_limit(self,source_id: str,next_allowed_at: int) -> None:
        self.db.execute("INSERT INTO source_rate(source_id,next_allowed_at) VALUES(?,?) ON CONFLICT(source_id) DO UPDATE SET "+
            "next_allowed_at=excluded.next_allowed_at",(source_id,next_allowed_at))

    def persist_evidence(self,document: dict,body_sha256: str,source_id: str,now: int) -> bool:
        raw=_canonical(document)
        if _sha(document.get("content","").encode("utf-8"))!=document.get("content_sha256"):
            raise ValueError("normalized evidence document is not content bound")
        fingerprint=_sha(raw.encode("utf-8"))
        path=self.documents/fingerprint[:2]/fingerprint
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            try:
                old=json.loads(path.read_text(encoding="utf-8"))
                if _sha(_canonical(old).encode("utf-8"))!=fingerprint or old!=document:raise ValueError("corrupt evidence file")
            except (OSError,ValueError,json.JSONDecodeError):
                path.unlink(missing_ok=True)
        if not path.exists():
            temp=path.with_suffix(".tmp")
            temp.write_text(raw+"\n",encoding="utf-8")
            temp.replace(path)
        stored=json.loads(path.read_text(encoding="utf-8"))
        if _sha(_canonical(stored).encode("utf-8"))!=fingerprint or stored!=document:
            raise ValueError("content-addressed evidence document hash mismatch")
        row=self.db.execute("SELECT * FROM evidence_versions WHERE document_fingerprint=?",(fingerprint,)).fetchone()
        if row:
            try: indexed=json.loads(row["document_json"])
            except (TypeError,ValueError,json.JSONDecodeError): indexed=None
            if indexed!=document or row["body_sha256"]!=body_sha256 or row["source_id"]!=source_id:
                self.db.execute("UPDATE evidence_versions SET content_sha256=?,body_sha256=?,document_json=?,source_id=?,recorded_at=? WHERE document_fingerprint=?",
                    (document["content_sha256"],body_sha256,raw,source_id,now,fingerprint))
            return False
        self.db.execute("INSERT INTO evidence_versions(document_fingerprint,content_sha256,body_sha256,document_json,source_id,recorded_at) VALUES(?,?,?,?,?,?)",
            (fingerprint,document["content_sha256"],body_sha256,raw,source_id,now))
        return True

    def evidence_version(self,document: dict) -> dict | None:
        fingerprint=_sha(_canonical(document).encode("utf-8"))
        row=self.db.execute("SELECT * FROM evidence_versions WHERE document_fingerprint=?",(fingerprint,)).fetchone()
        if not row:return None
        value=dict(row)
        try:
            stored=json.loads(value["document_json"])
            path=self.documents/fingerprint[:2]/fingerprint
            disk=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError,json.JSONDecodeError):
            return None
        if (stored!=document or disk!=stored or _sha(_canonical(disk).encode("utf-8"))!=fingerprint
                or value["content_sha256"]!=document.get("content_sha256")
                or _sha(document.get("content","").encode("utf-8"))!=document.get("content_sha256")):
            return None
        value["document"]=stored
        return value

    def evidence_document(self,content_sha256: str) -> dict | None:
        rows=self.db.execute("SELECT document_json FROM evidence_versions WHERE content_sha256=? ORDER BY document_fingerprint",(content_sha256,)).fetchall()
        if len(rows)>1:return None
        if rows:return json.loads(rows[0]["document_json"])
        row=self.db.execute("SELECT document_json FROM evidence WHERE content_sha256=?",(content_sha256,)).fetchone()
        return json.loads(row["document_json"]) if row else None


class _HTMLSourceReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.metadata=None
        self.claims=[]
        self.trims=[]
        self.completeness=None
        self.capture=None
        self.elements=[]
        self._occurrences={}

    def handle_starttag(self,tag,attrs):
        raw={k:v for k,v in attrs}
        a={k.replace("data-",""):v for k,v in attrs}
        if tag in {"source-document","claim","trim","complete-lineup","capture"}:
            line,column=self.getpos()
            ordinal=self._occurrences.get(tag,0)+1
            self._occurrences[tag]=ordinal
            self.elements.append({"tag":tag,"line":line,"column":column,"ordinal":ordinal,
                "raw_start_tag":self.get_starttag_text(),"attributes":raw,"normalized_lines":[]})
        if tag=="source-document": self.metadata=a
        elif tag=="claim": self.claims.append(a)
        elif tag=="trim": self.trims.append(a)
        elif tag=="complete-lineup": self.completeness=a
        elif tag=="capture": self.capture=a


def _int_or_none(value: str | None) -> int | None:
    if value in (None,"","NONE"):return None
    return int(value)


def _document_from_html(body: bytes,source: dict,local_ref: str) -> dict:
    parser=_HTMLSourceReader()
    parser.feed(body.decode("utf-8"))
    m=parser.metadata
    if not isinstance(m,dict):raise ValueError("HTML_SOURCE_METADATA_MISSING")
    kind=m.get("source-kind","SPEC_SHEET")
    completeness=m.get("completeness","SPEC_ONLY")
    lines=[]; doc={
      "schema_version":"1.0","document_id":m.get("document-id"),"source_id":source["source_id"],
      "source_authority":source["authority"],"market":source["market"],"model_id":m.get("model-id"),
      "generation_id":m.get("generation-id"),"trim_ids":[],"local_source_id":local_ref,
      "captured_at":m.get("captured-at"),"published_at":m.get("published-at") or None,
      "completeness":completeness,"source_kind":kind,"lineage_id":m.get("lineage-id") or m.get("document-id"),
      "edition_id":m.get("edition-id") or m.get("document-id"),
      "extraction_method":"CONTROLLED_LINE_READER_V1"}
    def bind(tag,index,line):
        element=[x for x in parser.elements if x["tag"]==tag][index:index+1]
        element=element[0] if element else None
        if element is not None:element["normalized_lines"].append(line)
    if kind=="SPEC_SHEET":
        for index,claim in enumerate(parser.claims):
            if not all(claim.get(k) for k in ("field","trim","value")):
                raise ValueError("HTML_CLAIM_INCOMPLETE")
            value=claim["value"]
            if claim.get("unit") and not re.search(r"\s"+re.escape(claim["unit"])+r"$",value):
                value+=f" {claim['unit']}"
            qualifier="|"+claim["qualifiers"] if claim.get("qualifiers") else ""
            line=f"claim|{claim['field']}|{claim['trim']}|{value}{qualifier}"
            lines.append(line); bind("claim",index,line)
        doc["trim_ids"]=sorted({c["trim"] for c in parser.claims if c.get("trim")})
    elif kind=="RETAIL_LINEUP":
        ids=[]; rows=[]
        for index,trim in enumerate(parser.trims):
            tid=trim.get("id")
            if not tid:raise ValueError("HTML_LINEUP_TRIM_ID_MISSING")
            ids.append(tid); line=f"lineup|trim|{tid}"; lines.append(line); bind("trim",index,line)
            rows.append({"market_trim_id":tid,"model_id":doc["model_id"],"generation_id":doc["generation_id"],
                "grade":trim.get("grade") or None,"powertrain":trim.get("powertrain"),
                "model_year":_int_or_none(trim.get("model-year")),"facelift_id":trim.get("facelift-id") or None})
        c=parser.completeness or {}
        scope_matches=(c.get("model-id")==doc["model_id"] and c.get("generation-id")==doc["generation_id"])
        complete=(c.get("publisher-declared-complete")=="true" and c.get("pagination-complete")=="true"
                  and c.get("expected-pages")==c.get("captured-pages") and bool(parser.capture) and scope_matches
                  and c.get("expected-pages","").isdigit() and int(c.get("expected-pages","0"))>0)
        model_year=c.get("model-year","NONE"); facelift=c.get("facelift-id","NONE")
        scope_record=(f"lineup_attestation|COMPLETE_CURRENT_THAI_RETAIL_LINEUP|model={doc['model_id']}|"
               f"generation={doc['generation_id']}|model_year={model_year}|facelift={facelift}")
        lines.append(scope_record); bind("complete-lineup",0,scope_record)
        capture=parser.capture or {}
        capture_id=capture.get("id","")
        capture_date=capture.get("captured-at",doc.get("captured_at", ""))
        edition=doc["edition_id"]
        capture_line=f"capture|edition={edition}|capture_id={capture_id}|captured_at={capture_date}|method=LOCAL_FIXTURE_CAPTURE"
        lines.append(capture_line); bind("capture",0,capture_line)
        doc["trim_ids"]=ids
        pages=int(c.get("captured-pages","0") or 0)
        doc["capture_manifest"]={"pagination_complete":complete,"source_page_count":pages,
                                 "row_count":len(ids),"listed_trim_ids":ids}
        doc["capture_provenance"]={"capture_id":capture_id,"capture_method":"LOCAL_FIXTURE_CAPTURE",
            "captured_at":capture_date,"captured_page_count":pages}
        doc["lineup_rows"]=rows
        if complete:
            doc["completeness"]="COMPLETE_LINEUP"
            complete_element=next((x for x in parser.elements if x["tag"]=="complete-lineup"),{})
            doc["completeness_evidence"]={"publisher_declared_complete":True,
                "assertion_type":"structured_attribute_assertion",
                "normalized_scope_record":scope_record,
                "raw_source_locator":f"html:{complete_element.get('line')}:{complete_element.get('column')}:complete-lineup#{complete_element.get('ordinal')}",
                "raw_source_sha256":_sha(body),"capture_status":"COMPLETE",
                "expected_page_count":pages,"captured_page_count":pages}
        else:
            doc["completeness"]="PARTIAL_TRIM_LIST"
    else:raise ValueError("HTML_SOURCE_KIND_UNSUPPORTED")
    doc["content"]="\n".join(lines)
    doc["content_sha256"]=_sha(doc["content"].encode("utf-8"))
    raw_text=body.decode("utf-8")
    metadata_element=next((x for x in parser.elements if x["tag"]=="source-document"),{})
    doc["source_representation"]={"kind":"STRUCTURED_HTML_ATTRIBUTES","raw_source_ref":local_ref,
        "raw_source_sha256":_sha(body),"raw_source_utf8":raw_text,
        "metadata_locator":f"html:{metadata_element.get('line')}:{metadata_element.get('column')}:source-document#{metadata_element.get('ordinal')}",
        "assertions":parser.elements}
    return doc


def _document_from_pdf_fixture(body: bytes,source: dict,local_ref: str) -> dict:
    payload=json.loads(body.decode("utf-8"))
    if payload.get("fixture_format")!="PDF_TEXT_FIXTURE_V1":raise ValueError("PDF_FIXTURE_FORMAT_UNSUPPORTED")
    pages=payload.get("pages")
    if not isinstance(pages,list) or not pages:raise ValueError("PDF_FIXTURE_PAGES_MISSING")
    numbered=[p.get("page") for p in pages]
    if numbered!=list(range(1,len(pages)+1)):raise ValueError("PDF_FIXTURE_PAGE_SEQUENCE_INVALID")
    metadata=payload.get("metadata")
    if not isinstance(metadata,dict) or metadata.get("source_kind")!="SPEC_SHEET":
        raise ValueError("PDF_FIXTURE_METADATA_INVALID")
    lines=[]
    for page in pages:
        text=page.get("text")
        if not isinstance(text,str):raise ValueError("PDF_FIXTURE_TEXT_INVALID")
        lines.extend(line.strip() for line in text.splitlines() if line.strip())
    if not lines or any(not line.startswith("claim|") for line in lines):
        raise ValueError("PDF_FIXTURE_CONTAINS_NON_CLAIM_TEXT")
    trims=sorted({line.split("|",3)[2] for line in lines})
    doc={"schema_version":"1.0","document_id":metadata.get("document_id"),
        "source_id":source["source_id"],"source_authority":source["authority"],"market":source["market"],
        "model_id":metadata.get("model_id"),"generation_id":metadata.get("generation_id"),
        "trim_ids":trims,"local_source_id":local_ref,"captured_at":metadata.get("captured_at"),
        "published_at":metadata.get("published_at"),"completeness":"SPEC_ONLY","source_kind":"SPEC_SHEET",
        "lineage_id":metadata.get("lineage_id",metadata.get("document_id")),
        "edition_id":metadata.get("edition_id",metadata.get("document_id")),
        "extraction_method":"CONTROLLED_LINE_READER_V1","content":"\n".join(lines)}
    doc["content_sha256"]=_sha(doc["content"].encode("utf-8"))
    return doc


class OfflineSourceAcquisitionAdapter:
    """Acquisition state machine bound to prerecorded fake HTTP and local storage."""
    def __init__(self,registry: dict,transport: DeterministicFakeHTTPTransport,
                 evidence_store: ContentAddressedEvidenceStore,policy: dict,clock):
        validate_source_registry(registry); validate_policy(policy)
        if not isinstance(transport,DeterministicFakeHTTPTransport) or transport.offline_only is not True:
            raise ValueError("source acquisition requires DeterministicFakeHTTPTransport")
        if getattr(clock,"now",None) is None:raise ValueError("source acquisition requires a fake clock")
        if policy["runner"]["external_http_enabled"] or policy["runner"]["paid_ai_enabled"]:
            raise ValueError("live/paid acquisition modes are disabled")
        self.registry,self.transport,self.store,self.policy,self.clock=registry,transport,evidence_store,policy,clock
        self.sources={s["source_id"]:s for s in registry["sources"]}

    def validate_url(self,source_id: str,url: str) -> tuple[dict,str | None]:
        source=self.sources.get(source_id)
        if source is None:return {},"SOURCE_NOT_ALLOWLISTED"
        try:
            parts=urlsplit(url)
            port=parts.port
        except Exception:return source,"URL_INVALID"
        if (parts.scheme!="https" or not parts.hostname or parts.username or parts.password or parts.query
                or parts.fragment or port not in (None,443)):
            return source,"URL_INVALID"
        host=parts.hostname.lower().rstrip(".")
        path=unquote(parts.path)
        if "\\" in path or any(part in {".",".."} for part in path.split("/")):
            return source,"URL_PATH_INVALID"
        if host not in source["host_allowlist"]:
            return source,"HOST_NOT_ALLOWLISTED"
        if not any(path.startswith(prefix) for prefix in source["path_prefix_allowlist"]):
            return source,"PATH_NOT_ALLOWLISTED"
        return source,None

    def _result(self,disposition: str,reason: str,**fields) -> dict:
        result={"disposition":disposition,"reason":reason,"external_http_calls":0,
                "paid_calls":0,"paid_tokens":0,"paid_spend_thb":0,"production_accesses":0,
                "canonical_writes":0,**fields}
        if disposition not in DISPOSITIONS:raise AssertionError("invalid acquisition disposition")
        return result

    def _valid_prior_success(self,result: dict,source: dict,source_id: str,url: str,
                             snapshot: dict,job: dict) -> bool:
        try:
            document=result["source_document"]
            local_ref=result["local_source_id"]
            raw=self.store.read_blob(local_ref)
            digest=_sha(raw)
            if (digest!=result.get("body_sha256") or local_ref!=f"fixture://cas/sha256/{digest}"
                    or source_id!=document.get("source_id") or result.get("request_url")!=url):return False
            content_type=result.get("content_type")
            if content_type not in source["allowed_content_types"]:return False
            if content_type=="text/html":derived=_document_from_html(raw,source,local_ref)
            elif content_type=="application/pdf":derived=_document_from_pdf_fixture(raw,source,local_ref)
            elif content_type=="application/json":
                derived=json.loads(raw.decode("utf-8"))
                if not isinstance(derived,dict) or derived.get("source_id")!=source_id:return False
                derived["local_source_id"]=local_ref
            else:return False
            if _canonical(derived)!=_canonical(document):return False
            if (document.get("source_authority")!=source["authority"] or document.get("market")!=source["market"]):return False
            _valid_document(document)
            if _document_scope_error(snapshot,job,document,document.get("content_sha256")):return False
            version=self.store.evidence_version(document)
            return bool(version and version["body_sha256"]==digest and version["source_id"]==source_id)
        except (KeyError,OSError,ValueError,TypeError,json.JSONDecodeError):
            return False

    def acquire(self,job: dict,*,source_id: str,url: str,snapshot: dict) -> dict:
        validate_fixture(snapshot)
        key=job.get("idempotency_key")
        if not isinstance(key,str) or not HEX64.fullmatch(key):
            return self._result("BLOCKED","JOB_IDEMPOTENCY_KEY_INVALID")
        source,url_error=self.validate_url(source_id,url)
        payload=job.get("payload",{})
        if payload.get("queue",job.get("queue"))=="RETAIL_AUDIT" or job.get("queue")=="RETAIL_AUDIT":
            generations=payload.get("generation_ids")
            if not isinstance(generations,list) or len(generations)!=1:
                return self._result("BLOCKED","RETAIL_AUDIT_REQUIRES_ONE_GENERATION",request_id=key)
        fingerprint=hashlib.sha256(_canonical({"source_id":source_id,"url":url,"payload":payload}).encode()).hexdigest()
        prior=self.store.get_request(key)
        now=int(self.clock.now())
        if prior and prior["request_fingerprint"]!=fingerprint:
            return self._result("BLOCKED","IDEMPOTENCY_SCOPE_MISMATCH",request_id=key)
        if url_error:
            if prior:return dict(prior["result"])
            result=self._result("BLOCKED",url_error,request_id=key,attempts=0)
            self.store.persist_request(key,fingerprint,source_id,url,"BLOCKED",0,None,result,now)
            return result
        if prior:
            if prior["status"] in {"FETCH_OK","UNCHANGED"}:
                cached=prior["result"]
                if self._valid_prior_success(cached,source,source_id,url,snapshot,job):
                    result=dict(cached); result.update(disposition="UNCHANGED",reason="IDEMPOTENT_REPLAY",
                        external_http_calls=0,request_id=key)
                    return result
                max_prior_attempts=min(source["retry_policy"]["maximum_attempts"],
                    self.policy["research"]["maximum_retries"]+1,
                    self.policy["runner"]["maximum_retries_per_job"]+1)
                if prior["attempts"]>=max_prior_attempts:
                    result=self._result("SOURCE_BROKEN","CACHED_EVIDENCE_INTEGRITY_RETRY_EXHAUSTED",
                        request_id=key,attempts=prior["attempts"],retryable=False)
                    self.store.persist_request(key,fingerprint,source_id,url,"SOURCE_BROKEN",prior["attempts"],None,result,now)
                    return result
                retry_at=max(now,self.store.get_rate_limit(source_id))
                result=self._result("BLOCKED","CACHED_EVIDENCE_INTEGRITY_RETRY_REQUIRED",request_id=key,
                    attempts=prior["attempts"],retry_at=retry_at,retryable=True)
                self.store.persist_request(key,fingerprint,source_id,url,"RETRY_WAIT",prior["attempts"],retry_at,result,now)
                prior=self.store.get_request(key)
            if prior["status"] in {"BLOCKED","SOURCE_BROKEN"}:
                return dict(prior["result"])
            if prior.get("retry_at") and now<int(prior["retry_at"]):
                return self._result("BLOCKED","RETRY_COOLDOWN",request_id=key,retry_at=prior["retry_at"],
                                    attempts=prior["attempts"])
        attempts=prior["attempts"] if prior else 0
        max_attempts=min(source["retry_policy"]["maximum_attempts"],
                         self.policy["research"]["maximum_retries"]+1,
                         self.policy["runner"]["maximum_retries_per_job"]+1)
        if attempts>=max_attempts:
            result=self._result("SOURCE_BROKEN","MAXIMUM_ATTEMPTS_EXHAUSTED",request_id=key,attempts=attempts)
            self.store.persist_request(key,fingerprint,source_id,url,"SOURCE_BROKEN",attempts,None,result,now)
            return result
        rate_until=self.store.get_rate_limit(source_id)
        if now<rate_until:
            return self._result("BLOCKED","SOURCE_RATE_LIMIT",request_id=key,retry_at=rate_until,attempts=attempts)
        day=utc_day(now); usage=self.store.usage(day)
        max_daily=min(source["rate_limit"]["maximum_requests_per_utc_day"],self.policy["runner"]["max_offline_requests_per_day"])
        if usage["requests"]>=max_daily:
            tomorrow=int(datetime.fromtimestamp(now,tz=timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())+86400
            return self._result("BLOCKED","DAILY_REQUEST_BUDGET_EXHAUSTED",request_id=key,retry_at=tomorrow,
                                attempts=attempts)
        if usage["elapsed_seconds"]>=self.policy["runner"]["max_elapsed_seconds_per_day"]:
            return self._result("BLOCKED","DAILY_ELAPSED_BUDGET_EXHAUSTED",request_id=key,
                                attempts=attempts)
        try:
            response=self.transport.get(url)
        except KeyError:
            result=self._result("SOURCE_BROKEN","NO_PRERECORDED_RESPONSE",request_id=key,
                                attempts=attempts+1,retryable=False)
            self.store.persist_request(key,fingerprint,source_id,url,"SOURCE_BROKEN",attempts+1,None,result,now)
            return result
        self.store.record_call(source_id,now,response.elapsed_seconds)
        interval=source["rate_limit"]["minimum_interval_seconds"]
        self.store.set_rate_limit(source_id,now+interval)
        attempts+=1
        if usage["elapsed_seconds"]+response.elapsed_seconds>self.policy["runner"]["max_elapsed_seconds_per_day"]:
            result=self._result("BLOCKED","DAILY_ELAPSED_BUDGET_EXHAUSTED",request_id=key,
                attempts=attempts,measured_usage={"requests":1,"elapsed_seconds":response.elapsed_seconds,
                "paid_tokens":0,"paid_spend_thb":0,"external_http_calls":0})
            self.store.persist_request(key,fingerprint,source_id,url,"RETRY_WAIT",attempts,
                now+source["retry_policy"]["cooldown_seconds"],result,now)
            return result
        if response.robots_allowed is not True:
            result=self._result("BLOCKED","ROBOTS_POLICY_DENIED",request_id=key,attempts=attempts)
            self.store.persist_request(key,fingerprint,source_id,url,"BLOCKED",attempts,None,result,now)
            return result
        if response.fixture_license not in source["allowed_fixture_licenses"]:
            result=self._result("BLOCKED","CONTENT_LICENSE_NOT_PERMITTED",request_id=key,attempts=attempts)
            self.store.persist_request(key,fingerprint,source_id,url,"BLOCKED",attempts,None,result,now)
            return result
        if 300<=response.status_code<400 or response.final_url is not None and response.final_url!=url:
            result=self._result("BLOCKED","REDIRECTS_DISABLED",request_id=key,attempts=attempts)
            self.store.persist_request(key,fingerprint,source_id,url,"BLOCKED",attempts,None,result,now)
            return result
        retry_after_cap=source["rate_limit"]["retry_after_cap_seconds"]
        if response.status_code==429:
            cooldown=max(source["retry_policy"]["cooldown_seconds"],min(response.retry_after_seconds,retry_after_cap))
            retry_at=now+cooldown
            self.store.set_rate_limit(source_id,retry_at)
            disposition="BLOCKED"
            status="RETRY_WAIT" if attempts<max_attempts else "BLOCKED"
            result=self._result(disposition,"RATE_LIMITED",request_id=key,attempts=attempts,retry_at=retry_at,
                                retryable=attempts<max_attempts)
            self.store.persist_request(key,fingerprint,source_id,url,status,attempts,retry_at if status=="RETRY_WAIT" else None,result,now)
            return result
        if response.status_code==206:
            status="RETRY_WAIT" if attempts<max_attempts else "SOURCE_BROKEN"
            result=self._result("PARTIAL","HTTP_PARTIAL_CONTENT",request_id=key,attempts=attempts,
                                retryable=attempts<max_attempts)
            retry_at=now+source["retry_policy"]["cooldown_seconds"] if status=="RETRY_WAIT" else None
            self.store.persist_request(key,fingerprint,source_id,url,status,attempts,retry_at,result,now)
            return result
        if response.status_code!=200:
            retryable=500<=response.status_code<600 and attempts<max_attempts
            status="RETRY_WAIT" if retryable else "SOURCE_BROKEN"
            result=self._result("SOURCE_BROKEN",f"HTTP_STATUS_{response.status_code}",request_id=key,
                                attempts=attempts,retryable=retryable)
            retry_at=now+source["retry_policy"]["cooldown_seconds"] if retryable else None
            self.store.persist_request(key,fingerprint,source_id,url,status,attempts,retry_at,result,now)
            return result
        content_type=response.headers.get("Content-Type","").split(";",1)[0].strip().lower()
        if content_type not in source["allowed_content_types"]:
            result=self._result("BLOCKED","CONTENT_TYPE_NOT_ALLOWLISTED",request_id=key,attempts=attempts)
            self.store.persist_request(key,fingerprint,source_id,url,"BLOCKED",attempts,None,result,now)
            return result
        body_digest=_sha(response.body)
        supplied=response.headers.get("X-Content-SHA256")
        if not isinstance(supplied,str) or not HEX64.fullmatch(supplied) or supplied!=body_digest:
            result=self._result("SOURCE_BROKEN","RESPONSE_BODY_HASH_MISMATCH",request_id=key,
                                body_sha256=body_digest,attempts=attempts)
            self.store.persist_request(key,fingerprint,source_id,url,"SOURCE_BROKEN",attempts,None,result,now)
            return result
        local_ref,_=self.store.put_blob(response.body)
        try:
            if content_type=="text/html":document=_document_from_html(response.body,source,local_ref)
            elif content_type=="application/pdf":document=_document_from_pdf_fixture(response.body,source,local_ref)
            elif content_type=="application/json":
                document=json.loads(response.body.decode("utf-8"))
                if not isinstance(document,dict):raise ValueError("JSON_SOURCE_DOCUMENT_INVALID")
                if document.get("source_id")!=source_id:raise ValueError("SOURCE_ID_MISMATCH")
                document["local_source_id"]=local_ref
            else:raise ValueError("CONTENT_TYPE_NOT_SUPPORTED")
            if (document.get("source_id")!=source_id or document.get("source_authority")!=source["authority"]
                    or document.get("market")!=source["market"]):
                raise ValueError("SOURCE_REGISTRY_METADATA_MISMATCH")
            _valid_document(document)
        except Exception as exc:
            result=self._result("SOURCE_BROKEN",f"MALFORMED_SOURCE_DOCUMENT:{type(exc).__name__}",
                                request_id=key,body_sha256=body_digest,attempts=attempts,
                                retryable=attempts<max_attempts)
            retry_at=now+source["retry_policy"]["cooldown_seconds"] if attempts<max_attempts else None
            self.store.persist_request(key,fingerprint,source_id,url,
                "RETRY_WAIT" if retry_at else "SOURCE_BROKEN",attempts,retry_at,result,now)
            return result
        scope_error=_document_scope_error(snapshot,job,document,document.get("content_sha256"))
        if scope_error:
            status="RETRY_WAIT" if attempts<max_attempts else "SOURCE_BROKEN"
            result=self._result("PARTIAL",scope_error,request_id=key,body_sha256=body_digest,
                                source_document=document,attempts=attempts,retryable=attempts<max_attempts)
            retry_at=now+source["retry_policy"]["cooldown_seconds"] if status=="RETRY_WAIT" else None
            self.store.persist_request(key,fingerprint,source_id,url,status,attempts,retry_at,result,now)
            return result
        inserted=self.store.persist_evidence(document,body_digest,source_id,now)
        disposition="FETCH_OK" if inserted else "UNCHANGED"
        result=self._result(disposition,"SOURCE_DOCUMENT_VALIDATED",request_id=key,attempts=attempts,
            body_sha256=body_digest,source_hash=document["content_sha256"],source_document=document,
            local_source_id=local_ref,content_type=content_type,request_url=url,
            measured_usage={"requests":1,"elapsed_seconds":response.elapsed_seconds,
              "paid_tokens":0,"paid_spend_thb":0,"external_http_calls":0})
        self.store.persist_request(key,fingerprint,source_id,url,disposition,attempts,None,result,now)
        return result
