# Security policy

## Project status

The RAG Marking Tool is a prototype. It has not been accredited and has not had an independent security review. Do not use it to process real classified, CUI, or otherwise controlled information without an authorization decision from your AO. Known limitations are listed in the README under "Known limitations and review items."

## Supported versions

| Version | Security fixes |
|---|---|
| 0.2.x | Yes |
| 0.1.x | No; upgrade to 0.2.x |

## Reporting a vulnerability

**Do not open a public issue, discussion, or pull request for a security problem.**

Report privately through this repository's **Security** tab: select **Report a vulnerability**. Only the maintainer sees the report.

**Never include classified, CUI, export-controlled, or real operational data in a report**, even as a sample. Reproduce the problem with synthetic documents and markings. A report containing controlled data will be deleted unread and treated as a spill on the reporter's side.

Please include:

- the version or commit hash;
- the operating system, database, and identity provider in use (local, AD tool mode, or AD directory mode);
- the AO policy settings in effect, if relevant (citation enforcement, review rule, ceiling mode, egress mode);
- steps to reproduce, using synthetic data;
- what the control should have done and what it did instead;
- your assessment of impact.

## What to expect

This project has one maintainer, so these are targets, not guarantees.

| Step | Target |
|---|---|
| Acknowledge the report | 5 business days |
| Initial assessment and severity | 10 business days |
| Fix for a critical or high finding | 30 days |
| Fix for a medium or low finding | Next planned release |

You'll be kept informed as the fix progresses. Once a fix is released, a GitHub security advisory will be published crediting you, unless you prefer not to be named. The default coordinated disclosure window is 90 days from the report, adjustable by agreement.

## Scope

The tool's purpose is to enforce controls, so the most valuable reports show a control being bypassed.

**In scope:**

- Retrieving or viewing content the user's clearance, citizenship, compartments, or need-to-know shouldn't allow (PDP bypass)
- A marking roll-up that produces a lower classification, or a less restrictive foreign-release marking, than its sources require
- Releasing a product without the required review: author self-approval, skipping the two-person rule, approving after content changed, or evading the policy version bound at submission
- Content above a model's ceiling or the system high reaching a model endpoint
- Prompts reaching an endpoint the egress policy should block, including through redirects or URL tricks
- Authentication bypass, session fixation or replay, NTLM accepted where Kerberos is required, cross-realm or service-principal sign-in, or an AD identity reaching a local account
- Altering or deleting governance or audit records without `verify-chain` detecting it
- The `ragmt_app` database role gaining privileges the installers don't grant
- Model credentials or session tokens exposed through the API, logs, or exports
- Injection (SQL, LDAP filter, XSS, header) or installer flaws that weaken the security of a default install

**Out of scope:**

- Findings that require an already compromised host, database superuser, or administrator account, unless they escalate further
- Items already listed under known limitations in the README
- Inaccurate or fabricated model output by itself. The citation checks and reviewer dispositions exist to catch that, so a report is in scope only when bad output gets past a control that should have stopped it, for example an uncited claim submitted under block mode, or prompt injection in a retrieved document that defeats a check.
- Denial of service from authenticated administrators, volumetric attacks, or missing rate limiting without a concrete exploit
- Vulnerabilities in third-party dependencies without a demonstrated path through this tool (report those upstream)
- Social engineering and physical attacks

## Safe harbor

Good-faith research on your own installation, using synthetic data, is welcome. Test only systems you own or have written authorization to test. Never test against government systems, a production deployment you don't administer, or any instance holding real controlled data. Research that follows this policy won't be pursued by the maintainer.
