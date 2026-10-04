# RAG Marking Tool user manual

Version 0.2.1, 4 Oct 2026

This manual covers day-to-day use of the RAG Marking Tool. Read [Getting started](#1-getting-started), then the section for your role. Your administrator tells you which roles you hold; you'll see them next to your name at the top of the screen.

| If you are a... | Read |
|---|---|
| Analyst who adds documents or drafts products | [Authors](#3-authors) |
| Person who checks drafts before release | [Reviewers](#4-reviewers) |
| Person with release authority | [Releasers](#5-releasers) |
| Authorizing Official | [Authorizing Officials](#6-authorizing-officials) |
| System administrator | [Administrators](#7-administrators) |
| Auditor or ISSO/ISSM | [Auditors](#8-auditors) |

---

## 1. Getting started

### Signing in with Windows

If your site uses Active Directory, the sign-in page shows **Sign in with Windows**.

1. Use a domain-joined computer, signed in with your domain account.
2. Open the address your administrator gave you and select **Sign in with Windows**.
3. You're signed in without typing a password. Your Windows sign-in proves who you are.

If you get "Windows sign-in was refused," your account either isn't set up in the tool yet or isn't in the right groups. Ask your administrator. If the page says your browser didn't offer Windows credentials, you're probably on a computer outside the domain, or the site hasn't been added to your browser's trusted intranet list.

### Signing in with a local account

1. Open the address your administrator gave you.
2. Enter your username and password and select **Sign in**.
3. The first time, you'll be asked to replace the temporary password. New passwords need at least 15 characters and 3 of these 4: lowercase, uppercase, digits, symbols. They can't contain your username.

If you see "invalid username or password," check both and try again. After a few failed tries (3 by default) your account locks for 15 minutes. An administrator can unlock it sooner. Lockout doesn't apply to Windows sign-in; your domain's own rules govern that.

### Staying signed in

- Sessions end after 15 minutes without activity (your AO may set 30 or 60).
- Every session ends after 8 hours regardless.
- **Refreshing the browser page signs you out.** That's deliberate: your session key is never stored in the browser.
- Select **Sign out** when you step away.

### Reading the screen

The yellow strip at the top is a standing reminder that the system needs an authorization decision before handling real classified data. Your clearance appears as a colored chip next to your name. Colors follow the standard banners: green U, blue C, red S, orange TS, yellow TS/SCI.

You only see tabs for your roles. The server checks every action anyway, so a missing tab means you don't need it, and a visible tab doesn't bypass any rule.

---

## 2. How the tool protects a product

Knowing the rules up front saves time.

- **You only see what you're cleared for.** Every search and every draft runs through an access check on your clearance, citizenship, compartments, and need-to-know groups. Results you can't see never reach you or the model.
- **Models only see what they're approved for.** Each model has a classification ceiling. If you're cleared for SECRET but pick a model approved for UNCLASSIFIED, SECRET material is held back from that model. The product records how many items were withheld.
- **Every sentence must trace to a source.** The model is told to cite sources as [S1], [S2], and so on. The tool checks every sentence. Sentences without a citation are flagged red. If the model cites a source number that doesn't exist, that's flagged as a fabricated citation and treated as uncited.
- **Nothing is marked for you by guesswork.** Cited sentences start with a marking rolled up from their sources. Uncited sentences start unmarked, and you can't submit until every sentence carries a portion marking.
- **Someone else must approve.** You can never approve or release your own product.
- **Everything is recorded.** Every draft, edit, review, and release goes into a tamper-evident log.

---

## 3. Authors

### 3.1 Adding a document (Intake tab)

1. Enter the title and source system.
2. Choose the banner classification and any document-level controls.
3. Add each section and choose its portion marking. Classification starts blank on purpose; pick one for every section.
4. Select **Ingest**. If a section is unmarked, or the banner doesn't cover the highest section, the form tells you what to fix.
5. After ingest, select **Embed** so the document becomes searchable.

You can't ingest anything above your own clearance or above the system's accredited level (system high).

### 3.2 Searching (Search tab)

Type a query and select **Search**. Each result shows its portion marking. Results are already filtered to what you may see, and every search is logged.

### 3.3 Drafting with a model (Draft tab)

1. Enter a **title** and your **question**. Write the question the way you'd task an analyst: specific subject, specific timeframe.
2. Pick a **model** from the drop-down. Each shows its ceiling, for example "Enclave Llama 3 (ceiling S)". If your question needs higher material than the ceiling allows, pick a model with a higher ceiling or expect withheld sources.
3. Pick how many **sources to retrieve** (8 is a good default).
4. Select **Draft**.

If the tool says no sources were available at or below the model's ceiling, everything relevant sat above that model's approval. Choose a different model.

### 3.4 Reading your draft

The draft opens with a banner bar showing the current overall marking. Below it:

- **Claims** (left). One block per sentence:
  - Green edge: cited. Select an **S** chip to open that source on the right.
  - Red edge, "No citation": the model gave no source.
  - Purple edge, "Analytic judgment": you've tagged it as your own assessment.
  - Red badge, "Model cited nonexistent S7": the model invented a source. Treat the sentence as unsupported.
- **Sources** (right). Select one to read the exact text the model was given.
- **AI-assistance disclosure.** Which model drafted this, the model version it reported, the ceiling applied, how many sources were withheld, and a fingerprint (hash) of the exact prompt.

**Read every cited source.** The tool confirms a sentence cites a real source you're cleared to see. It can't confirm the source actually says what the sentence claims. That judgment is yours, then the reviewer's.

### 3.5 Fixing claims

Each claim in a draft has these tools:

- **Marking picker.** Choose a level, an optional caveat (NOFORN, REL TO, ORCON, PROPIN, RELIDO, NOCON), and for REL TO, the country codes. Select **Apply**. For cited claims you can raise the marking but not lower it below "Floor from sources."
- **Tag as my analytic judgment.** Use this for a sentence that's your reasoning, not a sourced fact. A reviewer will have to accept it explicitly.
- **Delete claim.** Removes the sentence. The deletion is logged.

To strengthen an uncited sentence, delete it, or draft again with a sharper question so the model cites it.

### 3.6 Submitting for review

Select **Submit for review**. The button stays disabled while any claim is unmarked. Submission can still be refused:

| Message | What it means | What to do |
|---|---|---|
| "claims [3, 5] have no portion marking" | Some sentences are unmarked | Apply a marking to each |
| "policy blocks uncited claims at S" | Your AO requires every sentence to be cited at this level | Delete, re-draft, or tag the sentence as analytic judgment |
| "marking (U) is below the roll-up of the cited sources" | You tried to mark a sourced sentence lower than its sources | Use the floor marking or higher |

When submission succeeds, the product locks. The rules it's judged by (citation strictness, single or two-person review) are fixed at that moment, even if the AO changes policy later.

### 3.7 When a product comes back

If a reviewer returns your product, it reappears in **My products** as a draft with the reviewer's note in yellow. Make the changes and submit again. Reviewer decisions from the earlier round are cleared.

### 3.8 Exporting

Select **Export marked copy** to download a Markdown file. Until the product is released, the export carries a "NOT RELEASED: AI-ASSISTED DRAFT" line. See [Reading an exported product](#9-reading-an-exported-product).

---

## 4. Reviewers

### 4.1 Your queue

The **Review** tab lists products waiting for review, excluding your own. Products above your clearance don't appear.

### 4.2 What to check

1. Read the question, then each claim with its cited source open beside it. Confirm the source says what the claim says.
2. Look at the disclosure: was material withheld by the ceiling that might change the answer?
3. Check the portion markings and the banner.

### 4.3 Recording dispositions

Claims outlined in amber need your decision before you can approve. Which claims need one depends on the policy for the product's classification:

| Citation policy | Claims needing a disposition |
|---|---|
| Block | Analytic judgments, and any claim with a fabricated citation |
| Flag and acknowledge | Uncited claims, analytic judgments, and fabricated citations |
| Advisory | None (flags are informational) |

For each one, choose from the drop-down:

- **Verified against source material outside the tool.** You checked it against holdings the tool doesn't have.
- **Accepted as the author's analytic judgment.** The reasoning holds up.
- **Must be removed or corrected.** Blocks approval; return the product to the author.

Add a short note so the record shows why, then select **Record**. Your name goes into the log with each disposition.

### 4.4 Approving or returning

- **Approve and release** appears when the policy calls for a single reviewer. Your approval releases the product.
- **Approve** appears under two-person review. The product moves to the Release queue for a separate releaser.
- **Return to author** needs a reason. Use it whenever something must change, including any claim you marked for removal.

If someone edits a product after submission, approval is refused with "review invalidated." Return it and have the author resubmit.

---

## 5. Releasers

The **Release** tab lists products approved under two-person review. You won't see products you authored or reviewed. Open each one, confirm the review record and dispositions make sense, then select **Release** or **Return to author** with a note.

---

## 6. Authorizing Officials

### 6.1 The Risk policy page

Everyone can view the policy, but only an AO can change it. Each control is a drop-down. The risk statement for the selected option appears beside it, and changed fields turn yellow until saved.

**Release controls by classification** (one drop-down per level):

| Control | Options | What you're deciding |
|---|---|---|
| Citation enforcement | Block / Flag and acknowledge / Advisory | Whether uncited sentences stop submission, need a named reviewer's sign-off, or are only highlighted |
| Release review rule | Two-person / Single reviewer | Whether one person can both check and release, or the duties are split |

**Model controls:**

| Control | Options | What you're deciding |
|---|---|---|
| Model classification ceiling | Enforced per model / System-high | Whether each model is held to its own approved level, or all models run at the system high (only appropriate when every model sits inside the accredited boundary) |
| Model network egress | Local and enclave only / AO-approved allowlist | Whether any data may leave for a cloud model. Air-gapped sites keep "local only" |
| System high | U through TS/SCI | The highest level this installation may process |

**Account controls:** session idle timeout (15/30/60 minutes), failed sign-in lockout (3/5/10 attempts), and whether one person may hold both administrator and AO roles.

### 6.2 Saving a change

1. Change the drop-downs you need.
2. If any change is **less strict** than what's saved, a warning lists those items and asks for a justification (20 characters or more). Write it as you'd want it read in an assessment, for example: "Exercise network with synthetic data only, per ATO addendum 3, 3 Oct 2026."
3. Select **Save policy**.

The change applies to products submitted afterward. Products already in review keep the version they were submitted under. Every version, its author, and the justification appear in **History**.

### 6.3 Some controls can't be changed

The release gate itself, AI-assistance disclosure, audit logging, access filtering, and the rule against self-approval are always on. They're listed at the bottom of the page so assessors can see them.

### 6.4 Approving model endpoints

On the **Models** tab, endpoints outside the host or the declared enclave networks show "External" and "Pending." Under the allowlist egress policy, they can't be used until you select **Approve**. Before approving, confirm:

- the provider and region are authorized for the ceiling shown;
- the endpoint isn't foreign-hosted or foreign-operated if NOFORN material could fall under its ceiling (the tool checks classification level, not dissemination controls, per model);
- you didn't create the endpoint yourself (the tool won't let you approve your own).

**Revoke** removes approval and disables the endpoint immediately. If an administrator changes an approved endpoint's address, model, adapter, or ceiling, your approval clears automatically and you'll need to review it again.

---

## 7. Administrators

### 7.1 Managing users (Users tab)

**To add a user:**

1. Enter username and display name.
2. Choose the sign-in source:
   - **Local account:** the user signs in with a password you issue.
   - **Active Directory (Windows sign-in):** the username must match the user's Windows account name (sAMAccountName), in lowercase. No password is set in the tool. If your site runs AD in *directory mode*, you don't create these accounts at all: they're created at first sign-in from AD group membership, and attribute changes must be made in AD.
   - **OIDC / SAML:** can be created in advance, but can't sign in yet.
3. For local accounts, set a temporary password. The user must change it at first sign-in.
4. Tick roles. Under the default policy, one account can't hold both System administrator and Authorizing Official.
5. Set clearance, citizenship trigraph (for example USA), compartments, and need-to-know groups. **These attributes are what the access check uses**, so take them from the authoritative personnel record.
6. Select **Add user**.

Changing a user's attributes or roles signs them out everywhere. You can't change your own roles or disable yourself; another administrator has to.

An account's sign-in source can't be switched later. An AD sign-in will never open a local account with the same username, so plan names accordingly.

Other actions: **Unlock** a locked account, **Disable** or **Enable** an account, and **Reset password** to issue a new temporary password.

### 7.2 Adding a model endpoint (Models tab)

1. **Name:** something users will recognize, for example "Enclave Llama 3 70B".
2. **Adapter:** pick from the drop-down.
3. **Base URL** and **Model or deployment ID**. The placeholder shows an example for the chosen adapter.
4. **Approved classification ceiling:** the highest level this model is authorized for. It can't exceed the system high.
5. **Credential reference:** where the API key lives, never the key itself. Use `env:VARIABLE_NAME` (set in the service environment) or `file:C:\ProgramData\RagMT\secrets\openai.key` / `file:/etc/ragmt/keys/openai`. Leave blank for local servers that need no key. AWS Bedrock uses the service account's AWS credentials instead.
6. **Adapter options:** JSON when needed, for example `{"api_version": "2024-06-01"}` for Azure or `{"region": "us-gov-west-1"}` for Bedrock.
7. Select **Add endpoint**, then **Enable** it.

| Adapter | Typical base URL |
|---|---|
| OpenAI-compatible (Ollama, vLLM, llama.cpp, LM Studio, OpenAI) | `http://127.0.0.1:11434/v1` |
| Azure OpenAI | `https://<resource>.openai.azure.us` |
| Google Gemini / Vertex AI | `https://generativelanguage.googleapis.com/v1beta/models` |
| Anthropic | `https://api.anthropic.com` |
| AWS Bedrock | `https://bedrock-runtime.<region>.amazonaws.com` |

Endpoints that aren't on this machine must use HTTPS. Under the default "local only" egress policy, anything outside this machine or the enclave networks your installer declared is refused. Under the allowlist policy, an AO must approve it first.

---

## 8. Auditors

### 8.1 Governance log

The **Governance log** tab lists every policy change, model approval, account change, sign-in, and product step, newest first. Filter by type with the drop-down. Select a row to see its full details and hash.

Select **Verify chain integrity** to recompute the chain. "Chain intact" confirms no entry has been altered or removed. If it reports a break, **stop, preserve the database as is, and notify the ISSM.** The event number shown is the first altered entry.

### 8.2 What each product records

For any product you can reconstruct: who drafted it, with which model and version, the exact prompt fingerprint, which sources were used or withheld, each edit and marking change, each reviewer disposition with notes, the policy version applied, and who approved and released it. Filter the log by "Product workflow" and match the subject ID.

### 8.3 Query audit

Every search and every draft's retrieval step is also recorded in the query audit log (available through the API at `/audit/queries`), including the access decisions made for each result.

---

## 9. Reading an exported product

An export is a Markdown file laid out like this:

```
SECRET//NOFORN                                <- banner (top and bottom)

# Vessel Alpha cargo assessment

(U) Vessel Alpha docked at pier 4 on Monday. [S1]
(S//NOFORN) The manifest lists industrial pumps. [S2]
(U) This activity is likely routine. (Analytic judgment)

## Sources
Derived From: Multiple Sources
- [S1] (U) Harbor Report (document ..., ...)
- [S2] (S//NOFORN) Harbor Report (document ..., ...)

## AI-assistance disclosure
- Drafted with, model requested and reported, ceiling, withheld count, hashes

## Review record
- Author, policy version, reviewer, releaser, content hash
```

A line reading **NOT RELEASED: AI-ASSISTED DRAFT** means the product hasn't cleared the release gate. Don't disseminate it. Declassification instructions aren't generated; confirm them from the source documents before dissemination.

---

## 10. Troubleshooting

| You see | Why | What to do |
|---|---|---|
| "session expired or invalid" / back at sign-in | Idle timeout, 8-hour limit, page refresh, or an admin changed your account | Sign in again |
| "account locked" | Too many failed sign-ins | Wait 15 minutes or ask an administrator |
| "Windows sign-in was refused" | No matching tool account, wrong groups (directory mode), disabled AD account, or a non-Kerberos sign-in attempt | Administrator checks the governance log entry "auth.ad_refused" for the exact reason |
| "browser did not offer Windows credentials" | Computer isn't domain-joined, or the site isn't in the browser's intranet list | Use a domain computer; administrator adds the site by GPO |
| "requires role: reviewer" | Your account doesn't hold that role | Ask an administrator |
| "egress policy is local-only" | The chosen model is outside this machine and enclave | Use a local model, or ask the AO about the allowlist policy |
| "has not been approved by an AO" | External endpoint awaiting approval | Ask your AO |
| "non-loopback model endpoints must use HTTPS" | Endpoint configured with http:// | Administrator updates the URL |
| "no retrievable sources at or below the model's ceiling" | Everything relevant is above the model's approval | Choose a higher-ceiling model |
| "model endpoint unreachable" / "returned HTTP 401" | Network problem or bad credential reference | Administrator checks the endpoint and the referenced secret |
| "product not found" | It doesn't exist, or it's above your access | Confirm with the author |
| "review invalidated" | Content changed after submission | Return to author for resubmission |
| "chain broken at event N" | A governance record was altered | Preserve the system and notify the ISSM |

---

## 11. Glossary

| Term | Meaning |
|---|---|
| AO | Authorizing Official, who accepts risk on behalf of the organization |
| Analytic judgment | A sentence the author marks as their own reasoning, not a sourced fact |
| Banner | Overall classification and controls, shown top and bottom |
| Ceiling | Highest classification a model is approved to receive |
| Directory mode | AD setting where roles and attributes come from AD groups at each sign-in |
| Claim | One sentence of a drafted product |
| Disposition | A reviewer's recorded decision on a flagged claim |
| Egress | Data leaving this machine for a model endpoint |
| Enclave network | Internal networks the installer declared as local |
| Floor | Lowest marking allowed for a cited claim, rolled up from its sources |
| Governance log | Tamper-evident record of policy, account, model, and product events |
| Kerberos | The Windows domain sign-in protocol the tool accepts for AD users |
| PDP | Policy decision point: the component that decides what each user may see |
| Portion marking | Classification at the start of a paragraph or sentence, such as (S//NOFORN) |
| Roll-up | Combining several markings into the most restrictive one that covers them all |
| System high | Highest classification the installation is accredited to process |
