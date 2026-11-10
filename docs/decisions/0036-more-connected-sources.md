# 0036 · More connected sources: Nextcloud, SharePoint Server, CMIS, Git, ServiceNow, Jira

Status: accepted · 2026-11-07

## Context

Veyntora connected uploads, SharePoint Online, S3, websites, Confluence, databases and SMB shares. Organisations that keep their data in-house, German public bodies among them, often keep documents elsewhere:

- **Nextcloud** (also the file store of openDesk, the German government's office suite);
- **SharePoint on-premises** (2016, 2019, Subscription Edition), which the SharePoint Online connector cannot reach;
- **document management systems** (Alfresco, d.velop, enaio, OpenText), most of which speak CMIS;
- **documentation in Git**;
- **ticket knowledge** in ServiceNow and Jira.

Read-only MCP tools can already serve as knowledge tools (ADR 0035), but they cannot carry permissions or sync only what changed. Both matter for these systems.

## Decision

**1. Six new source types, all on the listing sync.**
- **The types:** `webdav`, `sharepoint_server`, `cmis`, `git`, `servicenow`, `jira`.
- **How they sync:** each is a reader that lists entries and downloads them. The existing listing sync does the rest:
  - store and scan;
  - index only what changed;
  - remove what is gone, and only after a complete listing;
  - apply permission changes without a re-index.
- **Limits:** each reader has a size cap. When the cap cuts a listing short, the sync removes nothing.

**2. Permissions: the system's own, mapped and fail closed, where they can be read.**
- **SharePoint Server:**
  - **Whose permissions count:** the role assignments with "View Items" (the `ViewListItems` bit). They come from the file, else from the nearest folder with its own permissions, else from the library. "Limited Access" grants nothing.
  - **Groups and claims:** AD groups and claims map through the group map, by login name, SID or title.
  - **SharePoint groups:** they map by name; an unmapped one counts by its members.
  - **Users:** they map by e-mail.
- **CMIS:**
  - **Who may read:** each document's ACL, for principals with read, write or all.
  - **Groups:** group principals map through the group map.
  - **Users:** user ids that are e-mail addresses map to that person.
- **What isn't mapped:** it is dropped and listed on the source, as for Confluence and SMB.

**3. The source's readers where the system's rules cannot be checked.**
- **Which sources:** Nextcloud/WebDAV, Git, ServiceNow and Jira use the source's readers and folder rules. The folder is a path: a WebDAV folder, `owner/repo/docs`, `knowledge base/category`, or `PROJECT`.
- **Why their permissions are not mapped:**
  - Nextcloud shares, repository permissions and Jira permission schemes do not map to documents reliably.
  - ServiceNow user criteria can be scripts, so Veyntora cannot evaluate them.
- **ServiceNow and Jira default to leaving restricted content out:**
  - **ServiceNow:** articles with their own "Can read" criteria, and articles in knowledge bases with "Can read" criteria, are left out.
  - **Jira:** issues with a security level are left out.
  - **Opting in:** an admin can include them, and the setting says that the source's readers then decide.

**4. No new dependencies.**
- **HTTP:** every connector uses httpx.
- **NTLM for SharePoint Server:** it uses pyspnego, already installed for the SMB connector. Basic sign-in over HTTPS is the alternative where IIS allows it.
- **Git:** the GitHub and GitLab APIs are used, with no clone and no git binary.
- **WebDAV XML:** it is parsed by the standard library. Any answer that carries a DTD is refused, so no entity can be declared or fetched.

**5. Secrets as before.** Each source's password or token goes to OpenBao, write-only, with the last 4 characters and an expiry shown.

## Consequences

- The connect page groups the 13 source types: files, pages and documents, tickets and records.
- Migration 0027 widens the `source_type` check.
- Tests run each reader against a mocked server through the real listing sync.
- None of the six has been run against a live system yet. Their responses follow the documented shapes, as Confluence's did when it was added.
- **Production follow-up:** a connection test against each customer's system before the first sync.
- **Not done:**
  - Nextcloud share mapping;
  - SharePoint Server change tokens: each sync lists every library;
  - Kerberos sign-in;
  - CMIS change logs;
  - ServiceNow user criteria.
- **When to revisit:** if customers need any of these.
