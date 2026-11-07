# Walkthroughs

Short screen recordings of Veyntora, made from a running install.

| GIF | Shows |
|---|---|
| [chat.gif](chat.gif) | The chat for employees: choose an assistant, ask, read the answer with its sources, approvals and settings |
| [connect-data-source.gif](connect-data-source.gif) | Connecting a data source: SharePoint Online, Git and Jira forms, readers, schedule; a source's documents |
| [create-chatbot.gif](create-chatbot.gif) | The five steps of a new chatbot: basics, knowledge, pipeline, access, test and publish |
| [user-management.gif](user-management.gif) | Users & groups: people, a person's access, roles, access reviews, a new group |
| [admin-console.gif](admin-console.gif) | A tour of the admin console, and resizing or folding its sidebar |

The recordings fill in forms to show them but never save, create or publish anything. Steps 2 to 5 of the chatbot wizard are shown for an existing chatbot.

## Recording them again

With the stack running and the dev users signed in by Playwright:

```bash
make walkthroughs
```

This signs in the e2e users, drives the UI with Playwright (`apps/web/scripts/record-walkthroughs.mjs`) and turns the frames into GIFs with Pillow (`scripts/walkthrough-gifs.py`). `WALKTHROUGH_BOT=<name>` picks the chatbot whose wizard steps are shown. The recordings show what is on the install, so record them on one without real people's data.
