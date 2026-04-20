"""
Consultation Report — Reg 5(2)(h).

Documents the applicant's compliance with the pre-application consultation
duties in the Planning Act 2008:
  - s.42 — duty to consult prescribed consultees, the relevant local
    authorities (s.43), and persons with an interest in the land (s.44);
  - s.47 — duty to consult the local community;
  - s.48 — duty to publicise the proposed application.

PINS Advice Notes relevant to this document:
  - AN-3   "Consultation and notification" (rev. 2024)
  - AN-6   "Preparation and submission of application documents" (rev. 2024)
  - AN-7   "Environmental Impact Assessment" (rev. 2024)
  - AN-8.x "Overview of the nationally significant infrastructure planning process" series
  - AN-11  "Working with public bodies" (rev. 2024)

Citation: "In fulfilment of Reg 5(2)(h) and section 37(3)(c) of the
Planning Act 2008 read with Reg 5(2) of the Infrastructure Planning
(Applications: Prescribed Forms and Procedure) Regulations 2009
(SI 2009/2264)."
"""

from __future__ import annotations

from datetime import datetime


def build_consultation_report(project: dict) -> dict:
    """Return a Consultation Report structure skeleton."""
    proj_name = project.get("name") or "[Project]"

    return {
        "document_title": "Consultation Report",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(h) and section 37(3)(c) of the "
            "Planning Act 2008 read with Regulation 5(2) of the Infrastructure "
            "Planning (Applications: Prescribed Forms and Procedure) Regulations "
            "2009 (SI 2009/2264)."
        ),
        "advice_notes": [
            "PINS Advice Note 3 — Consultation and notification (rev. 2024)",
            "PINS Advice Note 6 — Preparation and submission of application documents (rev. 2024)",
            "PINS Advice Note 7 — Environmental Impact Assessment (rev. 2024)",
            "PINS Advice Note 11 — Working with public bodies (rev. 2024)",
        ],
        "sections": [
            {
                "n": "1",
                "heading": "Introduction",
                "body": (
                    f"This Consultation Report records the pre-application consultation "
                    f"carried out by the undertaker in respect of the {proj_name} Development "
                    f"Consent Order 20xx. It demonstrates that the undertaker has complied "
                    f"with the consultation duties in sections 42, 47 and 48 of the Planning "
                    f"Act 2008, and has had regard to Advice Notes 3 and 11 of the Planning "
                    f"Inspectorate. The report also identifies responses received, how those "
                    f"responses have been taken into account in the proposed scheme, and how "
                    f"the undertaker has complied with section 49 of the Act (duty to have "
                    f"regard to responses)."
                ),
            },
            {
                "n": "2",
                "heading": "Consultation strategy",
                "body": (
                    "The undertaker's consultation strategy was informed by: (a) the PINS "
                    "pre-application advice meetings (AN-4); (b) discussions with the "
                    "relevant local authorities about the Statement of Community "
                    "Consultation (SoCC) per section 47(2); and (c) a Consultation Register "
                    "identifying the s.42 consultees prescribed in Schedule 1 to the "
                    "Infrastructure Planning (Applications: Prescribed Forms and Procedure) "
                    "Regulations 2009. [TO POPULATE — consultation zones map, dates of "
                    "pre-application meetings, AN-4 advice references.]"
                ),
            },
            {
                "n": "3",
                "heading": "Section 42 consultation — prescribed consultees",
                "body": (
                    "Under s.42(1)(a) of the 2008 Act, the undertaker consulted the persons "
                    "prescribed in Schedule 1 to the 2009 Regulations. The s.42 statutory "
                    "consultation was undertaken between [DATE] and [DATE] (a minimum 28-day "
                    "period per section 45). Responses received are tabulated in Appendix A "
                    "and summarised in Section 7 below."
                ),
                "tables": [
                    {
                        "title": "Table 3.1 — Section 42(1)(a) prescribed consultees contacted",
                        "columns": ["Schedule 1 ref", "Consultee", "Date contacted", "Response received", "Response summary"],
                        "rows": [
                            ["para (a)", "The Health and Safety Executive", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (b)", "The Environment Agency", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (c)", "Natural England", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (d)", "Historic England", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (e)", "The National Highways", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (f)", "Civil Aviation Authority", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (g)", "The relevant local highway authority", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (h)", "The relevant fire and rescue authority", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (i)", "The relevant police and crime commissioner", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (j)", "The relevant lead local flood authority", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (k)", "The relevant parish / community council", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (l)", "The relevant water / sewerage / gas / electricity undertakers", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (m)", "Ofgem (where relevant)", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (n)", "The Coal Authority (where relevant)", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                            ["para (o)", "Relevant Marine Management Organisation (where relevant)", "[DATE]", "[Y/N]", "[TO POPULATE]"],
                        ],
                    },
                ],
            },
            {
                "n": "4",
                "heading": "Section 42(1)(b) and s.43 — Local authorities",
                "body": (
                    "Under s.42(1)(b) and s.43, the undertaker consulted each local authority "
                    "within whose area the proposed development is located ('B authority'), "
                    "and each local authority sharing a boundary with a 'B authority' ('A "
                    "authority'). The relevant authorities are set out in Table 4.1 below."
                ),
                "tables": [
                    {
                        "title": "Table 4.1 — Local authorities consulted under ss.42(1)(b)/43",
                        "columns": ["Authority", "Role", "Date contacted", "Response received"],
                        "rows": [
                            ["[TO POPULATE]", "B authority (host LPA)", "[DATE]", "[Y/N]"],
                            ["[TO POPULATE]", "A authority (neighbouring)", "[DATE]", "[Y/N]"],
                            ["[TO POPULATE]", "County council (two-tier)", "[DATE]", "[Y/N]"],
                            ["[TO POPULATE]", "Parish council", "[DATE]", "[Y/N]"],
                        ],
                    },
                ],
            },
            {
                "n": "5",
                "heading": "Section 42(1)(d) and s.44 — Persons with an interest in the land",
                "body": (
                    "Under s.42(1)(d) and s.44, the undertaker consulted each person with an "
                    "interest in the land within the proposed Order limits (Category 1), each "
                    "person who could make a claim under Part 1 of the Land Compensation Act "
                    "1973 (Category 2), and each person who could make a claim under section "
                    "10 of the Compulsory Purchase Act 1965 (Category 3). These persons are "
                    "listed in the Book of Reference (Reg 5(2)(i)). The land interest "
                    "consultation was carried out by diligent inquiry per section 44(5) and "
                    "the methodology is set out in Appendix B of this report. [TO POPULATE — "
                    "number of Cat 1 / 2 / 3 consultees, response rates.]"
                ),
            },
            {
                "n": "6",
                "heading": "Section 47 — Consultation with the local community (SoCC)",
                "body": (
                    "Under s.47 the undertaker prepared a Statement of Community Consultation "
                    "('SoCC') setting out how it proposed to consult people living in the "
                    "vicinity of the proposed development. The SoCC was developed in "
                    "consultation with the relevant local authorities under s.47(2) between "
                    "[DATE] and [DATE], and was published on [DATE] by way of: "
                    "(a) a notice in [local newspaper]; (b) making a copy available for "
                    "inspection at [venue]; and (c) on the project website. "
                    "The community consultation was then carried out in accordance with the "
                    "SoCC between [DATE] and [DATE] — a minimum 28-day period per s.47(7). "
                    "Consultation methods included: public exhibitions at [venues], a project "
                    "website, a freepost response address, a dedicated phone line, and pop-up "
                    "events at [locations]. [TO POPULATE — public attendance figures, response "
                    "counts, methodology per SoCC.]"
                ),
            },
            {
                "n": "7",
                "heading": "Section 48 — Publicity",
                "body": (
                    "Under s.48 the undertaker publicised the proposed application by "
                    "publishing a notice in the prescribed form: "
                    "(a) once in the London Gazette; "
                    "(b) for at least 2 successive weeks in a local newspaper circulating "
                    "in the vicinity of the land; "
                    "(c) once in a national newspaper; and "
                    "(d) on the project website. "
                    "The s.48 notices were published on [DATE] with the 28-day response "
                    "deadline ending on [DATE]. Copies of the notices are at Appendix C."
                ),
            },
            {
                "n": "8",
                "heading": "Section 49 — How responses have been taken into account",
                "body": (
                    "Section 49 requires the undertaker, in deciding whether the application "
                    "it proposes to submit should be in the same terms as the proposed "
                    "application, to have regard to any relevant response received. A "
                    "Consultation Response Register and a response-by-response change log is "
                    "set out in Appendix D. In summary, the following changes were made to "
                    "the scheme in response to consultation feedback: [TO POPULATE — top 10 "
                    "scheme changes, e.g. layout moved away from heritage asset, cable route "
                    "rerouted to avoid ancient woodland, construction compound reduced]."
                ),
            },
            {
                "n": "9",
                "heading": "Statutory undertakers and s.44(5) diligent inquiry",
                "body": (
                    "The methodology used to identify Category 1, 2 and 3 persons for the "
                    "purposes of sections 42(1)(d) and 44 is set out in Appendix B. It "
                    "comprised: HM Land Registry Official Copy of Title Register searches for "
                    "each freehold and registered leasehold title within the proposed Order "
                    "limits; INSPIRE index polygons for unregistered parcels; CCOD (Companies "
                    "and Commercial Ownership Dataset) searches for corporate owners; "
                    "Commons Register searches; and on-site inquiry with occupiers."
                ),
            },
            {
                "n": "10",
                "heading": "Accessibility and equalities",
                "body": (
                    "The consultation was designed to be accessible in accordance with the "
                    "Equality Act 2010. Materials were made available in large print and "
                    "alternative formats on request. Pop-up events were held at accessible "
                    "venues. A British Sign Language interpreter was available at [event(s)]. "
                    "The Equality Impact Assessment confirming accessibility is at Appendix E."
                ),
            },
            {
                "n": "11",
                "heading": "Conclusion",
                "body": (
                    "The undertaker considers that it has complied fully with the duties in "
                    "sections 42, 43, 44, 47, 48 and 49 of the Planning Act 2008 and has had "
                    "proper regard to the Advice Notes of the Planning Inspectorate. The "
                    "scheme submitted for development consent reflects the responses received "
                    "and is materially improved as a result of the consultation process."
                ),
            },
        ],
        "appendices": [
            {"id": "A", "title": "Consultation Register — all consultees and responses"},
            {"id": "B", "title": "Land Interest Identification Methodology (s.44 diligent inquiry)"},
            {"id": "C", "title": "s.48 Publicity Notices (London Gazette / local / national press)"},
            {"id": "D", "title": "Consultation Response Register and Change Log"},
            {"id": "E", "title": "Equality Impact Assessment"},
            {"id": "F", "title": "Statement of Community Consultation (SoCC)"},
            {"id": "G", "title": "Public Exhibition Materials"},
        ],
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
