# Canadian Disclosure Ingestion Assessment

> **Status:** Phase 4 assessment completed on 2026-08-21 UTC. Automated SEDAR+
> public-website ingestion is disabled. This is an engineering access decision,
> not legal advice.

## Sources reviewed

The assessment used official material only:

- the [SEDAR+ homepage](https://www.sedarplus.com/);
- the complete **SEDAR+ Terms of Use**, last updated April 28, 2023, published as
  an [official CSA PDF](https://www.securities-administrators.ca/wp-content/uploads/2023/02/SEDAR_Terms_of_Use.pdf);
- the **SEDAR+ Privacy Statement**, published as an
  [official CSA PDF](https://www.securities-administrators.ca/wp-content/uploads/2023/05/UPDATED-Privacy-Statement.pdf);
  and
- official SEDAR+ resource material describing general public access and the Data
  Distribution Service.

The current `robots.txt` explicitly disallows several named crawlers but does not
state a general grant for other automation. Robots directives are not a license,
so the Terms of Use control this design. An attempted read of an official help
page also reached a bot-protection CAPTCHA/block page. It was not solved or
bypassed, and no further public-site probing was performed.

## Access finding

The public website supports browser-based public search and individual downloads,
including limited unaltered extracts for research under conditions. That permission
does not fit Kalki's planned automated evidence database. The official terms:

- prohibit robots, spiders, automatic devices, scraping, and automated searches;
- prohibit using public information to construct or populate a database;
- restrict repeated access, mass distribution, commercialization, and deep links;
- impose privacy obligations for personal information; and
- allow access or use to be revoked and content removal to be required.

The official privacy statement identifies two possible routes that could support
broader data use: a subscription-based Data Distribution Service under a license,
or an ad-hoc request approved by the CSA under its own terms. Neither route is
currently approved, configured, or known to be zero-cost. Obtaining one could
require manual contact, legal acceptance, privacy review, and payment, so this
project did not create an account, contact the CSA, or accept an agreement.

## Decision and fallback

There is no live SEDAR+ public-site client. `UnavailableSedarPlusProvider` fails
closed before network access and explains that a separately reviewed licensed or
approved source is required. Manual SEDAR+ downloads are not offered as a database
import workaround because the same public-site terms restrict database storage.

Canadian coverage remains incomplete. Permitted fallbacks are:

1. issuer investor-relations pages and official releases, each after its own access,
   retention, and redistribution review;
2. provincial securities-regulator publications where their terms allow the
   intended use; and
3. SEC filings for Canadian issuers that file in the United States, while clearly
   labeling that subset as SEC coverage rather than complete Canadian disclosure.

These fallbacks must use separate provider adapters and must not claim SEDAR+
completeness. Email alerts can help a human discover filings, but they do not grant
automated retrieval or database rights.

## Future authorized provider contract

Phase 4 defines a source-neutral `SedarPlusProvider` protocol without copying or
reverse-engineering a proprietary SEDAR+ response schema. A future implementation
may be enabled only after its exact agreement is reviewed and recorded.

Every accepted disclosure envelope must include:

- `licensed_distribution` or `approved_ad_hoc` access mode;
- an agreement reference and explicit automation, database-storage, and public-
  redistribution rights;
- agreement expiry where applicable;
- provider profile and document identifiers;
- issuer name, optional LEI, reporting jurisdictions, and every listing separately;
- filing/publication timestamps with offsets, language, media type, length,
  document-content hash, and source-record hash; and
- an authorized locator only if the agreement permits it.

Normalization refuses expired agreements or envelopes that do not explicitly
allow both automation and database storage. Public redistribution remains a
separate flag and is never inferred from retrieval permission.

## Identifier and time mapping

The future provider profile ID is the primary source-specific identity. An LEI is
supporting evidence when supplied. Legal name and ticker are not sufficient to
merge entities: names change, symbols are reused, and one issuer can have multiple
listings. The normalizer therefore creates a mapping candidate keyed by the
provider namespace/profile ID and leaves cross-provider entity resolution for an
audited later layer.

Filing timestamps are normalized to UTC while retaining their semantic role.
When an authorized feed supplies a distinct public-availability timestamp, it is
preserved. Otherwise availability defaults conservatively to retrieval time. The
contracts reject filing/public/retrieval sequences that would introduce future
knowledge.

## Tests and fixtures

The tracked fixture is entirely synthetic and does not contain or imitate a real
issuer, filing, agreement, licensed response, or SEDAR+ document. It exercises the
future contract's multiple listings, jurisdictions, LEI, Eastern-offset timestamp,
rights, and source hash. Tests prove:

- the current provider fails before any network request;
- missing, expired, or insufficient rights fail closed;
- timestamps normalize to UTC without look-ahead;
- identifiers remain explicit and same-name profiles do not collapse; and
- normalized schemas are closed and immutable.

## Reassessment gate

Revisit this decision only if the user provides a written authorization/license or
explicitly approves contacting the CSA about the Data Distribution Service. Before
implementation, record cost, permitted automation, retention, derivative use,
public display, personal-information handling, attribution, deletion duties,
technical interface, credentials, rate limits, and termination/rollback terms.
