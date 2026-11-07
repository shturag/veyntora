"""Nextcloud/WebDAV, SharePoint Server, CMIS, Git (GitHub and GitLab), ServiceNow and
Jira (ADR 0036), each against a mocked server and through the listing sync: what is
read, what is left out, and who may read it (mapped and fail closed, or the source's
readers and folder rules)."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from veyntora_api.db.models.knowledge import DataSource, Document
from veyntora_api.knowledge import connectors
from veyntora_api.knowledge.service import SourceAcl
from veyntora_workers.connectors.cmis import CmisReader, readers_of
from veyntora_workers.connectors.git import GitReader, document_name
from veyntora_workers.connectors.jira import JiraReader, jql_of
from veyntora_workers.connectors.listing import sync_listing
from veyntora_workers.connectors.servicenow import ServiceNowReader
from veyntora_workers.connectors.sharepoint_server import NtlmAuth, SharePointServerReader
from veyntora_workers.connectors.webdav import WebdavReader

from tests.test_ingestion import CTX, World
from tests.test_sharepoint import Writer


@pytest.fixture
async def world(db: Any) -> World:
    return await World(db).setup()


async def _source(w: World, kind: str, settings: Any, **extra: Any) -> DataSource:
    return await connectors.create_connected_source(
        w.db,
        CTX,
        Writer(),  # type: ignore[arg-type]
        connectors.ConnectedSourceInput(
            name=f"{kind}-{uuid4().hex[:6]}",
            type=kind,  # type: ignore[arg-type]
            secret="s3cr3t-value-0000",  # type: ignore[arg-type]
            **{kind: settings},
            **extra,
        ),
        w.user.id,
    )


async def _docs(w: World, source: DataSource) -> dict[str, Document]:
    rows = await w.db.execute(sa.select(Document).where(Document.source_id == source.id))
    return {d.path: d for d in rows.scalars()}


def _readers(w: World) -> SourceAcl:
    return SourceAcl(groups=[w.group.id], users=[])


# ---------------------------------------------------------------- Nextcloud / WebDAV

ROOT = "/remote.php/dav/files/bot"


def _dav(href: str, *, folder: bool = False, etag: str = "e1", fileid: str = "") -> str:
    kind = "<d:collection/>" if folder else ""
    size = "" if folder else "<d:getcontentlength>12</d:getcontentlength>"
    return (
        f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
        f"<d:resourcetype>{kind}</d:resourcetype><d:getetag>&quot;{etag}&quot;</d:getetag>"
        f"<d:getlastmodified>Thu, 01 Oct 2026 08:00:00 GMT</d:getlastmodified>{size}"
        f"<oc:fileid>{fileid}</oc:fileid></d:prop></d:propstat></d:response>"
    )


def _multistatus(*items: str) -> bytes:
    return (
        '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
        + "".join(items)
        + "</d:multistatus>"
    ).encode()


DAV: dict[str, bytes] = {
    f"{ROOT}/Policies/": _multistatus(
        _dav(f"{ROOT}/Policies/", folder=True),
        _dav(f"{ROOT}/Policies/Leave%20policy.md", fileid="41"),
        _dav(f"{ROOT}/Policies/HR/", folder=True),
    ),
    f"{ROOT}/Policies/HR/": _multistatus(
        _dav(f"{ROOT}/Policies/HR/", folder=True),
        _dav(f"{ROOT}/Policies/HR/Salaries.md", fileid="42"),
    ),
}


def _webdav(req: httpx.Request) -> httpx.Response:
    assert req.headers["authorization"].startswith("Basic ")
    if req.method == "PROPFIND":
        assert req.headers["depth"] == "1"
        body = DAV.get(req.url.path)
        return httpx.Response(207, content=body) if body else httpx.Response(404)
    return httpx.Response(200, content=b"# Policy\n\nText")


async def test_webdav_lists_folders_and_applies_folder_rules(world: World) -> None:
    w = world
    cfg = connectors.WebdavSettings(
        base_url="https://cloud.example.com", username="bot", include_paths=["/Policies/"]
    )
    assert cfg.include_paths == ["Policies"]
    source = await _source(
        w,
        "webdav",
        cfg,
        acl=_readers(w),
        folders=[connectors.FolderReaders(path="Policies/HR", groups=[w.other_group.id])],
    )
    reader = WebdavReader(cfg, "app-password", transport=httpx.MockTransport(_webdav))
    assert "readable" in await reader.check()
    stats = await sync_listing(w.ingestor(), source, reader.listing())
    await reader.close()
    assert stats["changed"] == 2
    docs = await _docs(w, source)
    leave = docs["Policies/Leave policy.md"]
    assert leave.url == "https://cloud.example.com/index.php/f/41"
    assert leave.acl == {"users": [], "groups": [str(w.group.id)]}
    assert docs["Policies/HR/Salaries.md"].acl == {"users": [], "groups": [str(w.other_group.id)]}


async def test_webdav_refuses_a_dtd() -> None:
    cfg = connectors.WebdavSettings(base_url="https://dav.example.com/files", username="bot")
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><d:multistatus/>'
    reader = WebdavReader(
        cfg, "pw", transport=httpx.MockTransport(lambda _: httpx.Response(207, content=evil))
    )
    with pytest.raises(RuntimeError, match="DTD"):
        await reader.check()
    await reader.close()


# ---------------------------------------------------------------- SharePoint Server

SITE = "https://sp.corp.example/sites/hr"
LIB = "11111111-2222-3333-4444-555555555555"
READ = {"BasePermissions": {"Low": "138612833", "High": "176"}, "Name": "Read"}
LIMITED = {"BasePermissions": {"Low": "1011030016", "High": "0"}, "Name": "Limited Access"}


def _ra(member: dict[str, Any], *bindings: dict[str, Any]) -> dict[str, Any]:
    return {"Member": member, "RoleDefinitionBindings": list(bindings)}


SP_ROUTES: dict[str, Any] = {
    "/sites/hr/_api/web": {"Title": "HR", "ServerRelativeUrl": "/sites/hr"},
    "/sites/hr/_api/web/lists": {"value": [{"Id": LIB, "Title": "Documents", "RootFolder": {}}]},
    f"/sites/hr/_api/web/lists(guid'{LIB}')/items": {
        "value": [
            {
                "Id": 1,
                "FileRef": "/sites/hr/Shared Documents/Leave.docx",
                "FileLeafRef": "Leave.docx",
                "FSObjType": 0,
                "Modified": "2026-10-01T08:00:00Z",
                "File_x0020_Size": "10",
            },
            {
                "Id": 2,
                "FileRef": "/sites/hr/Shared Documents/Board",
                "FSObjType": 1,
                "HasUniqueRoleAssignments": True,
            },
            {
                "Id": 3,
                "FileRef": "/sites/hr/Shared Documents/Board/Minutes.docx",
                "FileLeafRef": "Minutes.docx",
                "FSObjType": 0,
                "Modified": "2026-10-02T08:00:00Z",
            },
        ]
    },
    f"/sites/hr/_api/web/lists(guid'{LIB}')/RoleAssignments": {
        "value": [
            _ra(
                {"PrincipalType": 4, "LoginName": "c:0+.w|s-1-5-21-9-513", "Title": "CORP\\staff"},
                READ,
            ),
            _ra({"PrincipalType": 8, "Id": 7, "Title": "HR Members"}, READ),
            _ra(
                {"PrincipalType": 1, "LoginName": "i:0#.w|corp\\x", "Email": "x@corp.example"},
                LIMITED,
            ),
        ]
    },
    f"/sites/hr/_api/web/lists(guid'{LIB}')/items(2)/RoleAssignments": {
        "value": [
            _ra(
                {"PrincipalType": 4, "LoginName": "c:0+.w|s-1-5-21-9-777", "Title": "CORP\\board"},
                READ,
            )
        ]
    },
    "/sites/hr/_api/web/sitegroups/GetById(7)/users": {
        "value": [{"PrincipalType": 1, "LoginName": "i:0#.w|corp\\a", "Email": "a@example.com"}]
    },
}


def _sp(req: httpx.Request) -> httpx.Response:
    if "/GetFileByServerRelativeUrl('/sites/hr/Shared Documents/" in req.url.path:
        return httpx.Response(200, content=b"PK\x03\x04 a docx")
    route = SP_ROUTES.get(req.url.path)
    return httpx.Response(200, json=route) if route is not None else httpx.Response(404)


async def test_sharepoint_server_maps_role_assignments(world: World) -> None:
    w = world
    cfg = connectors.SharePointServerSettings(
        site_url=SITE,
        username="CORP\\svc",
        auth="basic",
        group_map={"S-1-5-21-9-513": w.group.id},
    )
    source = await _source(w, "sharepoint_server", cfg)
    reader = SharePointServerReader(cfg, "pw", w.db, transport=httpx.MockTransport(_sp))
    assert "1 document libraries" in await reader.check()
    stats = await sync_listing(w.ingestor(), source, reader.listing())
    await reader.close()
    assert stats["changed"] == 2
    docs = await _docs(w, source)
    # The library: the mapped AD group (by SID) and the SharePoint group's member by
    # e-mail; "Limited Access" does not let anyone read.
    assert docs["Shared Documents/Leave.docx"].acl == {
        "users": [str(w.user.id)],
        "groups": [str(w.group.id)],
    }
    assert docs["Shared Documents/Leave.docx"].url == (
        "https://sp.corp.example/sites/hr/Shared%20Documents/Leave.docx"
    )
    # Below a folder with its own permissions: only the board, which is not mapped.
    assert docs["Shared Documents/Board/Minutes.docx"].acl == {"users": [], "groups": []}
    assert "group CORP\\board" in source.config["unmapped"]


def test_ntlm_sign_in_starts_with_a_negotiate_message() -> None:
    flow = NtlmAuth("CORP\\svc", "pw").auth_flow(httpx.Request("GET", SITE))
    first = next(flow)
    assert first.headers["Authorization"].startswith("NTLM TlRMTVNTUAAB")  # NTLMSSP, type 1


# ---------------------------------------------------------------- CMIS

BROWSER = "https://dms.example.com/alfresco/api/-default-/public/cmis/versions/1.1/browser"
CMIS_ROOT = BROWSER + "/root"


def _obj(oid: str, name: str, kind: str, **more: Any) -> dict[str, Any]:
    props = {"cmis:objectId": oid, "cmis:name": name, "cmis:baseTypeId": kind, **more}
    return {"object": {"succinctProperties": props}}


def _aces(*entries: tuple[str, list[str]]) -> dict[str, Any]:
    return {
        "aces": [{"principal": {"principalId": p}, "permissions": perms} for p, perms in entries]
    }


# (address, cmisselector, objectId) -> the answer.
CMIS: dict[tuple[str, str, str], Any] = {
    (BROWSER, "", ""): {
        "-default-": {
            "repositoryId": "-default-",
            "repositoryName": "Main",
            "rootFolderUrl": CMIS_ROOT,
        }
    },
    (CMIS_ROOT + "/Sites/hr", "object", ""): {"succinctProperties": {"cmis:objectId": "f-hr"}},
    (CMIS_ROOT, "children", "f-hr"): {
        "hasMoreItems": False,
        "objects": [
            _obj(
                "d1;2.0",
                "Leave.pdf",
                "cmis:document",
                **{
                    "cmis:versionSeriesId": "d1",
                    "cmis:contentStreamLength": 9,
                    "cmis:changeToken": "t2",
                    "cmis:lastModificationDate": 1790000000000,
                },
            ),
            _obj("f-pay", "Pay", "cmis:folder"),
        ],
    },
    (CMIS_ROOT, "children", "f-pay"): {
        "hasMoreItems": False,
        "objects": [
            _obj(
                "d2;1.0",
                "Bands.pdf",
                "cmis:document",
                **{"cmis:versionSeriesId": "d2", "cmis:contentStreamLength": 9},
            )
        ],
    },
    (CMIS_ROOT, "acl", "d1;2.0"): _aces(
        ("GROUP_hr", ["cmis:read"]), ("a@example.com", ["cmis:write"])
    ),
    (CMIS_ROOT, "acl", "d2;1.0"): _aces(
        ("GROUP_pay", ["cmis:all"]), ("GROUP_hr", ["{http://x}custom"])
    ),
    # Downloads ask for the listed version's object, not the version series.
    (CMIS_ROOT, "content", "d1;2.0"): b"%PDF-1.4 x",
    (CMIS_ROOT, "content", "d2;1.0"): b"%PDF-1.4 x",
}


def _cmis(req: httpx.Request) -> httpx.Response:
    p = req.url.params
    key = (str(req.url).split("?", 1)[0], p.get("cmisselector", ""), p.get("objectId", ""))
    answer = CMIS.get(key)
    if answer is None:
        return httpx.Response(404)
    if isinstance(answer, bytes):
        return httpx.Response(200, content=answer)
    return httpx.Response(200, json=answer)


async def test_cmis_maps_acls_and_downloads_the_latest_version(world: World) -> None:
    w = world
    cfg = connectors.CmisSettings(
        browser_url=BROWSER,
        username="svc",
        folders=["/Sites/hr"],
        group_map={"GROUP_hr": w.group.id},
    )
    source = await _source(w, "cmis", cfg)
    reader = CmisReader(cfg, "pw", w.db, transport=httpx.MockTransport(_cmis))
    assert "Main" in await reader.check()
    stats = await sync_listing(w.ingestor(), source, reader.listing())
    await reader.close()
    assert stats["changed"] == 2
    docs = await _docs(w, source)
    assert docs["Sites/hr/Leave.pdf"].external_id == "d1"
    assert docs["Sites/hr/Leave.pdf"].acl == {
        "users": [str(w.user.id)],
        "groups": [str(w.group.id)],
    }
    # A custom permission is not read access; GROUP_pay is not mapped: nobody.
    assert docs["Sites/hr/Pay/Bands.pdf"].acl == {"users": [], "groups": []}
    assert "principal GROUP_pay" in source.config["unmapped"]


def test_cmis_readers_need_a_read_permission() -> None:
    acl = {"aces": [{"principal": {"principalId": "x"}, "permissions": ["cmis:none"]}]}
    assert readers_of(acl) == set()


# ---------------------------------------------------------------- Git

GH_TREE = {
    "truncated": False,
    "tree": [
        {"path": "README.md", "type": "blob", "sha": "b1", "size": 20},
        {"path": "docs/guide.rst", "type": "blob", "sha": "b2", "size": 20},
        {"path": "docs/img", "type": "tree", "sha": "t1"},
        {"path": "src/main.py", "type": "blob", "sha": "b3", "size": 20},
        {"path": "docs/setup.md", "type": "blob", "sha": "b4", "size": 20},
    ],
}


def _github(req: httpx.Request) -> httpx.Response:
    assert req.headers["authorization"] == "Bearer tok"
    path = req.url.path
    if path == "/repos/acme/handbook":
        return httpx.Response(200, json={"default_branch": "main"})
    if path == "/repos/acme/handbook/git/trees/main":
        return httpx.Response(200, json=GH_TREE)
    if path.startswith("/repos/acme/handbook/git/blobs/"):
        assert req.headers["accept"] == "application/vnd.github.raw+json"
        return httpx.Response(200, content=f"Doc {path[-2:]}\n".encode())
    return httpx.Response(404)


async def test_github_reads_documents_only(world: World) -> None:
    w = world
    cfg = connectors.GitSettings(repositories=["acme/handbook"], include_paths=["docs"])
    source = await _source(w, "git", cfg, acl=_readers(w))
    reader = GitReader(cfg, "tok", transport=httpx.MockTransport(_github))
    assert "branch main" in await reader.check()
    stats = await sync_listing(w.ingestor(), source, reader.listing())
    await reader.close()
    assert stats["changed"] == 2
    docs = await _docs(w, source)
    assert set(docs) == {"acme/handbook/docs/guide.rst", "acme/handbook/docs/setup.md"}
    assert docs["acme/handbook/docs/setup.md"].url == (
        "https://github.com/acme/handbook/blob/main/docs/setup.md"
    )
    assert docs["acme/handbook/docs/guide.rst"].mime_type == "text/plain"
    assert docs["acme/handbook/docs/setup.md"].external_version == "b4"


def _gitlab(req: httpx.Request) -> httpx.Response:
    assert req.headers["private-token"] == "tok"
    raw = req.url.raw_path.decode()
    if raw == "/api/v4/projects/it%2Fdocs":
        return httpx.Response(200, json={"default_branch": "main"})
    if raw.startswith("/api/v4/projects/it%2Fdocs/repository/tree"):
        if "page_token" not in str(req.url):
            nxt = "https://git.example.com/api/v4/projects/it%2Fdocs/repository/tree?page_token=2"
            return httpx.Response(
                200,
                json=[{"id": "g1", "path": "a.md", "type": "blob"}],
                headers={"Link": f'<{nxt}>; rel="next"'},
            )
        return httpx.Response(200, json=[{"id": "g2", "path": "b/c.md", "type": "blob"}])
    if "/repository/blobs/" in raw:
        return httpx.Response(200, content=b"# Text\n")
    return httpx.Response(404)


async def test_gitlab_follows_pages(world: World) -> None:
    w = world
    cfg = connectors.GitSettings(
        provider="gitlab", base_url="https://git.example.com", repositories=["it/docs"]
    )
    source = await _source(w, "git", cfg, acl=_readers(w))
    reader = GitReader(cfg, "tok", transport=httpx.MockTransport(_gitlab))
    stats = await sync_listing(w.ingestor(), source, reader.listing())
    await reader.close()
    assert stats["changed"] == 2
    docs = await _docs(w, source)
    assert docs["it/docs/b/c.md"].url == "https://git.example.com/it/docs/-/blob/main/b/c.md"


def test_git_settings_and_document_names() -> None:
    with pytest.raises(ValidationError, match="owner/repository"):
        connectors.GitSettings(repositories=["handbook"])
    assert document_name("docs/a.mdx") == "a.mdx.md"
    assert document_name("src/app.py") is None
    assert document_name("Guide.PDF") == "Guide.PDF"


# ---------------------------------------------------------------- ServiceNow


def _article(sid: str, number: str, kb: str, **more: Any) -> dict[str, Any]:
    return {
        "sys_id": sid,
        "number": number,
        "short_description": f"Article {number}",
        "text": f"<p>How to {number}</p>",
        "sys_updated_on": "2026-10-01 08:00:00",
        "sys_mod_count": "4",
        "can_read_user_criteria": "",
        "kb_knowledge_base": kb,
        "kb_knowledge_base.title": {"kb1": "IT", "kb2": "HR"}[kb],
        "kb_category.label": "VPN",
        **more,
    }


def _servicenow(req: httpx.Request) -> httpx.Response:
    table = req.url.path.rsplit("/", 1)[-1]
    q = req.url.params
    if table == "kb_knowledge_base":
        return httpx.Response(
            200,
            json={"result": [{"sys_id": "kb1", "title": "IT"}, {"sys_id": "kb2", "title": "HR"}]},
        )
    if table == "kb_uc_can_read_mtom":
        assert "kb1,kb2" in q["sysparm_query"]
        return httpx.Response(200, json={"result": [{"kb_knowledge_base": "kb2"}]})
    if table == "kb_knowledge":
        assert "workflow_state=published" in q["sysparm_query"]
        return httpx.Response(
            200,
            json={
                "result": [
                    _article("a1", "KB001", "kb1"),
                    _article("a2", "KB002", "kb1", can_read_user_criteria="uc9"),
                    _article("a3", "KB003", "kb2"),
                ]
            },
        )
    return httpx.Response(404)


async def test_servicenow_leaves_restricted_articles_out(world: World) -> None:
    w = world
    cfg = connectors.ServiceNowSettings(instance_url="https://acme.service-now.com", username="svc")
    source = await _source(w, "servicenow", cfg, acl=_readers(w))
    reader = ServiceNowReader(cfg, "pw", transport=httpx.MockTransport(_servicenow))
    assert "2 knowledge bases" in await reader.check()
    stats = await sync_listing(w.ingestor(), source, reader.listing())
    await reader.close()
    assert stats["changed"] == 1
    [doc] = (await _docs(w, source)).values()
    # Own "Can read" criteria (KB002) and a restricted knowledge base (KB003): left out.
    assert doc.path == "IT/VPN/KB001"
    assert doc.url == "https://acme.service-now.com/kb_view.do?sysparm_article=KB001"
    assert doc.acl == {"users": [], "groups": [str(w.group.id)]}


async def test_servicenow_names_missing_knowledge_bases() -> None:
    cfg = connectors.ServiceNowSettings(
        instance_url="https://acme.service-now.com", username="svc", knowledge_bases=["Legal"]
    )
    reader = ServiceNowReader(cfg, "pw", transport=httpx.MockTransport(_servicenow))
    with pytest.raises(RuntimeError, match="legal"):
        await reader.check()
    await reader.close()


# ---------------------------------------------------------------- Jira


def _issue(key: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": key.replace("HELP-", "10"),
        "key": key,
        "fields": {
            "summary": f"Printer {key}",
            "updated": "2026-10-01T08:00:00.000+0200",
            "project": {"key": "HELP"},
            "status": {"name": "Done"},
            "comment": {"comments": [{"author": {"displayName": "Ana"}}]},
            **fields,
        },
        "renderedFields": {
            "description": "<p>It jams.</p>",
            "comment": {"comments": [{"body": "<p>Restart it.</p>"}]},
        },
    }


def _jira_cloud(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/rest/api/2/project/HELP":
        return httpx.Response(200, json={"name": "Help desk"})
    if req.url.path == "/rest/api/3/search/jql":
        assert req.url.params["expand"] == "renderedFields"
        if "nextPageToken" not in req.url.params:
            return httpx.Response(
                200, json={"issues": [_issue("HELP-1")], "nextPageToken": "p2", "isLast": False}
            )
        return httpx.Response(
            200,
            json={"issues": [_issue("HELP-2", security={"name": "Staff only"})], "isLast": True},
        )
    return httpx.Response(404)


async def test_jira_reads_solved_issues_and_skips_secured_ones(world: World) -> None:
    w = world
    cfg = connectors.JiraSettings(
        base_url="https://acme.atlassian.net", email="bot@acme.com", projects=["HELP"]
    )
    assert jql_of(cfg) == 'project in ("HELP") AND (statusCategory = Done) ORDER BY key ASC'
    source = await _source(w, "jira", cfg, acl=_readers(w))
    reader = JiraReader(cfg, "tok", transport=httpx.MockTransport(_jira_cloud))
    assert "Help desk" in await reader.check()
    stats = await sync_listing(w.ingestor(), source, reader.listing())
    await reader.close()
    assert stats["changed"] == 1
    [doc] = (await _docs(w, source)).values()
    assert doc.path == "HELP/HELP-1" and doc.url == "https://acme.atlassian.net/browse/HELP-1"
    assert doc.acl == {"users": [], "groups": [str(w.group.id)]}


async def test_jira_data_center_pages_by_offset() -> None:
    cfg = connectors.JiraSettings(
        flavour="datacenter", base_url="https://jira.example.com", projects=["HELP"], jql=""
    )
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer pat"
        seen.append(req.url.params["startAt"])
        start = int(req.url.params["startAt"])
        return httpx.Response(200, json={"total": 2, "issues": [_issue(f"HELP-{start + 1}")]})

    reader = JiraReader(cfg, "pat", transport=httpx.MockTransport(handler))
    keys = [e.path async for e in reader.entries()]
    await reader.close()
    assert keys == ["HELP/HELP-1", "HELP/HELP-2"] and seen == ["0", "1"]
    assert reader.listed_all


def test_jira_settings() -> None:
    with pytest.raises(ValidationError, match="e-mail"):
        connectors.JiraSettings(base_url="https://a.atlassian.net", projects=["HELP"])
    with pytest.raises(ValidationError, match="project key"):
        connectors.JiraSettings(flavour="datacenter", base_url="https://j.example", projects=["x"])
    with pytest.raises(ValidationError, match="ORDER BY"):
        connectors.JiraSettings(
            flavour="datacenter",
            base_url="https://j.example",
            projects=["HELP"],
            jql="status = Done order by created",
        )


def test_every_connected_kind_has_settings() -> None:
    assert set(connectors.KINDS) == {t.value for t in connectors.MODELS}
    assert json.dumps(sorted(connectors.KINDS))
