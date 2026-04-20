"""
Draft Development Consent Order — Reg 5(2)(c).

Produces a skeleton DCO (the "Order") with the typical article structure
used across the Rampion 2, Sunnica, Gate Burton, Mallard Pass and Longfield
solar/energy DCOs, plus the prescribed schedules (authorised development,
requirements, protective provisions, compulsory acquisition, deemed
marine licence if offshore).

The instrument is titled: "The [Project] Development Consent Order 20xx"
and is expressed as a statutory instrument made under s.114(1) and s.115
of the Planning Act 2008. The recitals cite PA 2008 s.37, s.55, s.117,
and the accepting / examination / recommendation chain.

Citation: "In fulfilment of Reg 5(2)(c) of the Infrastructure Planning
(Applications: Prescribed Forms and Procedure) Regulations 2009
(SI 2009/2264)."
"""

from __future__ import annotations

from datetime import datetime


def build_draft_order(project: dict, *, cpo_sought: bool = False, deemed_marine_licence: bool = False) -> dict:
    """Return a structured draft DCO per the typical PINS solar/BESS order."""
    proj_name = project.get("name") or "[Project name — TO POPULATE]"
    order_title = f"The {proj_name} Development Consent Order 20xx"

    preamble = {
        "title": order_title,
        "si_number": "20xx No. [NNNN]",
        "made_date": "[TO POPULATE — made date]",
        "coming_into_force_date": "[TO POPULATE — coming-into-force date]",
        "recitals": [
            "An application has been made to the Secretary of State in accordance with the Planning Act 2008 and the Infrastructure Planning (Applications: Prescribed Forms and Procedure) Regulations 2009 for an Order granting development consent.",
            f"The application was accepted for examination on [DATE] and assigned PINS reference [EN0101XX] for {proj_name}.",
            "Following examination by a Panel / Single Inspector appointed under Schedule 4 to the Act, a recommendation was made to the Secretary of State on [DATE].",
            "The Secretary of State, having considered the report of the Examining Authority and all material considerations, has decided to make this Order.",
        ],
        "making_power": "The Secretary of State, in exercise of the powers conferred by sections 114, 115, 117, 120 and 122 of, and paragraphs 1 to 3 and 10 to 19 of Schedule 5 to, the Planning Act 2008, makes the following Order —",
    }

    parts = [
        _part(1, "Preliminary", [
            _article(1, "Citation and commencement", "This Order may be cited as the "
                     f"{order_title} and comes into force on [DATE]."),
            _article(2, "Interpretation", "In this Order, definitions shall apply per Schedule 1 "
                     "and include: 'the authorised development', 'the Order land', 'the undertaker', "
                     "'the relevant planning authority', 'the highway authority', and such other "
                     "terms as appear in the Schedule."),
        ]),
        _part(2, "Principal powers", [
            _article(3, "Development consent etc. granted by the Order",
                     "Subject to the provisions of this Order and to the requirements in "
                     "Schedule 2, the undertaker is granted development consent for the "
                     "authorised development described in Schedule 1 within the Order limits."),
            _article(4, "Maintenance of authorised development",
                     "The undertaker may, within the Order limits, from time to time maintain "
                     "the authorised development, except that this article does not authorise any "
                     "maintenance to the extent that it would give rise to any materially new or "
                     "materially different environmental effects from those identified in the "
                     "environmental statement."),
            _article(5, "Operation of generating station",
                     "The undertaker is authorised to use and operate the generating station "
                     "comprised in the authorised development."),
            _article(6, "Benefit of Order",
                     "Subject to article 7, the provisions of this Order conferring benefit on "
                     "the undertaker shall have effect solely for the benefit of the undertaker."),
            _article(7, "Consent to transfer benefit of Order",
                     "With the consent of the Secretary of State, the undertaker may transfer to "
                     "another person any or all of the benefit of the provisions of this Order "
                     "and such related statutory rights as may be agreed between the undertaker "
                     "and the transferee."),
        ]),
        _part(3, "Streets", [
            _article(8, "Application of the 1980 Act",
                     "Where a street is temporarily stopped up, diverted or altered under this "
                     "Order, the Highways Act 1980 provisions shall apply subject to the "
                     "modifications set out in Schedule 3."),
            _article(9, "Street works", "The undertaker may, for the purposes of the authorised "
                     "development, enter on any street within the Order limits and — (a) break up "
                     "or open the street, or any sewer, drain or tunnel under it; (b) tunnel or "
                     "bore under the street; (c) place apparatus in the street; (d) maintain, "
                     "renew or remove apparatus in the street; (e) execute any works required "
                     "for or incidental to any of those purposes."),
            _article(10, "Temporary stopping up of streets", "The undertaker may, during and "
                     "for the purposes of carrying out the authorised development, temporarily "
                     "stop up, alter or divert any street and may for any reasonable time — "
                     "(a) divert the traffic from the street; and (b) subject to paragraph (2), "
                     "prevent all persons from passing along the street."),
            _article(11, "Access to works", "The undertaker may, for the purposes of the "
                     "authorised development, form and lay out means of access, or improve "
                     "existing means of access, in the locations specified in Schedule 4 "
                     "(access and rights of way)."),
        ]),
        _part(4, "Supplemental powers", [
            _article(12, "Discharge of water", "The undertaker may use any watercourse or any "
                     "public sewer or drain for the discharge of water from the authorised "
                     "development, subject to the consent of the owner of the watercourse or the "
                     "relevant sewerage undertaker."),
            _article(13, "Protective works to buildings", "Subject to the following provisions "
                     "of this article, the undertaker may at its own expense carry out such "
                     "protective works to any building lying within the Order limits as it "
                     "considers necessary or expedient."),
            _article(14, "Authority to survey and investigate the land",
                     "The undertaker may for the purposes of this Order enter on any land "
                     "shown on the land plans and within the Order limits for the purposes of — "
                     "(a) surveying and investigating the land; (b) without limitation to the "
                     "scope of sub-paragraph (a), making trial holes in such positions on the "
                     "land as the undertaker thinks fit to investigate the nature of the surface "
                     "layer and subsoil."),
            _article(15, "Felling or lopping of trees and removal of hedgerows",
                     "The undertaker may fell or lop any tree or shrub, or cut back its roots, "
                     "or remove any hedgerow, within or overhanging land within the Order limits "
                     "if it reasonably believes it to be necessary to do so to prevent the "
                     "tree or shrub — (a) obstructing or interfering with the construction, "
                     "maintenance or operation of the authorised development; or (b) "
                     "constituting a danger to persons using it."),
        ]),
    ]

    if cpo_sought:
        parts.append(_part(5, "Powers of acquisition", [
            _article(16, "Compulsory acquisition of land",
                     "The undertaker may acquire compulsorily so much of the Order land as is "
                     "required for the authorised development, or to facilitate it, or is "
                     "incidental to it."),
            _article(17, "Compulsory acquisition of rights",
                     "Subject to article 21, the undertaker may acquire such rights over the "
                     "Order land as may be required for any purpose for which that land may be "
                     "acquired under article 16, by creating them as well as by acquiring rights "
                     "already in existence."),
            _article(18, "Private rights",
                     "Subject to the provisions of this article, all private rights over land "
                     "subject to compulsory acquisition under this Order are extinguished — "
                     "(a) as from the date of acquisition of the land by the undertaker, whether "
                     "compulsorily or by agreement; or (b) on the date of entry on the land by "
                     "the undertaker under section 11(1) of the Compulsory Purchase Act 1965."),
            _article(19, "Application of the Compulsory Purchase (Vesting Declarations) Act 1981",
                     "The Compulsory Purchase (Vesting Declarations) Act 1981 applies as if this "
                     "Order were a compulsory purchase order."),
            _article(20, "Acquisition of subsoil or airspace only",
                     "The undertaker may acquire compulsorily so much of, or such rights in, the "
                     "subsoil of or the airspace over the land referred to in article 16 as may "
                     "be required for any purpose for which that land may be acquired under that "
                     "provision, instead of acquiring the whole of the land."),
            _article(21, "Rights under or over streets", "The power conferred by article 17 "
                     "includes power to acquire such rights over, under or along any street as "
                     "may be required for the purposes of the authorised development."),
            _article(22, "Temporary use of land for carrying out the authorised development",
                     "The undertaker may, in connection with the carrying out of the authorised "
                     "development, temporarily take possession of the land specified in columns "
                     "(1) and (2) of Schedule 6 (land of which temporary possession may be taken) "
                     "for the purpose specified in column (3)."),
            _article(23, "Time limit for exercise of authority to acquire land compulsorily",
                     "After the end of the period of 5 years beginning on the day on which this "
                     "Order is made — (a) no notice to treat is to be served under Part 1 of the "
                     "1965 Act; and (b) no declaration is to be executed under section 4 of the "
                     "Compulsory Purchase (Vesting Declarations) Act 1981."),
        ]))

    parts.append(_part(len(parts) + 1, "Miscellaneous and general", [
        _article(90, "Application of landlord and tenant law",
                 "The Landlord and Tenant Act 1954 and any other enactment relating to rights "
                 "of tenants in respect of the land subject to the Order are to have effect "
                 "subject to this article."),
        _article(91, "Operational land for purposes of the 1990 Act",
                 "Development consent granted by this Order is to be treated as specific planning "
                 "permission for the purposes of section 264(3)(a) of the 1990 Act (cases in which "
                 "land is to be treated as operational land)."),
        _article(92, "Defence to proceedings in respect of statutory nuisance",
                 "Where proceedings are brought under section 82(1) of the Environmental "
                 "Protection Act 1990 in relation to a nuisance falling within paragraph (g) of "
                 "section 79(1) of that Act (noise emitted from premises so as to be prejudicial "
                 "to health or a nuisance), no order is to be made, and no fine may be imposed, "
                 "under section 82(2) of that Act if the defendant shows that the nuisance — "
                 "(a) relates to premises used by the undertaker for the purposes of or in "
                 "connection with the construction or maintenance of the authorised development "
                 "and that the nuisance is attributable to the carrying out of the authorised "
                 "development in accordance with a notice served under section 60 of the "
                 "Control of Pollution Act 1974."),
        _article(93, "Protective provisions", "Schedule 9 (protective provisions) has effect."),
        _article(94, "Certification of plans etc.",
                 "The undertaker must, as soon as practicable after the making of this Order, "
                 "submit to the Secretary of State copies of — the book of reference, the "
                 "design and access statement, the environmental statement, the land plans, "
                 "the works plans, the access and rights of way plans, and the other plans "
                 "referred to in this Order for certification that they are true copies of "
                 "those documents referred to in this Order."),
        _article(95, "Service of notices",
                 "A notice or other document required or authorised to be served for the "
                 "purposes of this Order may be served — (a) by post; (b) by delivering it "
                 "to the person on whom it is to be served or to whom it is to be given or "
                 "supplied; or (c) with the consent of the recipient and subject to paragraphs "
                 "(6) and (7), by transmitting it electronically."),
        _article(96, "Arbitration",
                 "Any difference under any provision of this Order, unless otherwise provided "
                 "for, is to be referred to and settled in arbitration in accordance with the "
                 "Arbitration Act 1996 by a single arbitrator to be agreed between the parties, "
                 "or, failing agreement, to be appointed on the application of either party "
                 "(after giving notice in writing to the other) by the Secretary of State."),
        _article(97, "Requirements",
                 "Development consent granted by this Order is subject to the requirements set "
                 "out in Schedule 2 (requirements)."),
    ]))

    schedules = [
        _schedule(1, "Authorised development", _authorised_development_description(project)),
        _schedule(2, "Requirements", _requirements_schedule()),
        _schedule(3, "Streets subject to street works", "[TO POPULATE — list of streets with grid references]"),
        _schedule(4, "Access and rights of way", "[TO POPULATE — schedule of new/improved accesses]"),
        _schedule(5, "Land in which only new rights etc. may be acquired", "[TO POPULATE — cross-reference Book of Reference Category 2]"),
        _schedule(6, "Land of which temporary possession may be taken", "[TO POPULATE — cross-reference Book of Reference Category 3]"),
        _schedule(7, "Modification of compensation and compulsory purchase enactments for creation of new rights", "The enactments for the time being in force with respect to compensation for the compulsory purchase of land apply as if references in those enactments to the compensation for the compulsory purchase of land included references to the compensation for the compulsory purchase of new rights or the imposition of restrictive covenants."),
        _schedule(8, "Hedgerows", "[TO POPULATE — schedule of hedgerows subject to removal]"),
        _schedule(9, "Protective provisions", _protective_provisions()),
        _schedule(10, "Documents to be certified", _certified_documents_list()),
    ]

    if deemed_marine_licence:
        schedules.append(_schedule(11, "Deemed Marine Licence", "[TO POPULATE per Marine and Coastal Access Act 2009 Part 4, Chapter 2 — conditions, monitoring, licence fee]"))

    return {
        "document_title": "Draft Development Consent Order",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(c) of the Infrastructure Planning "
            "(Applications: Prescribed Forms and Procedure) Regulations 2009 "
            "(SI 2009/2264, as amended)."
        ),
        "primary_act": "Planning Act 2008 c.29 ss.114, 115, 117, 120, 122 and Schedule 5",
        "order_title": order_title,
        "preamble": preamble,
        "parts": parts,
        "schedules": schedules,
        "cpo_sought": cpo_sought,
        "deemed_marine_licence": deemed_marine_licence,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _part(n: int, heading: str, articles: list[dict]) -> dict:
    return {"n": n, "heading": heading, "articles": articles}


def _article(n: int, heading: str, body: str) -> dict:
    return {"n": n, "heading": heading, "body": body}


def _schedule(n: int, heading: str, body) -> dict:
    return {"n": n, "heading": heading, "body": body}


def _authorised_development_description(project: dict) -> str:
    tech = (project.get("workload_type") or project.get("technology") or "solar").lower()
    cap = project.get("capacity_mw") or "[CAP]"
    name = project.get("name") or "[Project]"
    if tech == "solar":
        return (
            f"A Nationally Significant Infrastructure Project as defined in sections 14(1)(a) "
            f"and 15(2) of the 2008 Act comprising — \n"
            f"Work No. 1 — a solar photovoltaic generating station with a nameplate capacity "
            f"of up to {cap} MW comprising: (a) solar photovoltaic module tables mounted on "
            f"fixed or single-axis tracking frames; (b) inverter and transformer stations; "
            f"(c) internal DC and AC cabling; (d) internal access tracks; and (e) ancillary "
            f"infrastructure.\n"
            f"Work No. 2 — an electricity storage facility comprising battery energy storage "
            f"system containers, power conversion system units, fire suppression and HVAC.\n"
            f"Work No. 3 — an on-site substation compound including transformer, circuit "
            f"breakers, control building, earthing and lightning protection.\n"
            f"Work No. 4 — underground and/or overhead grid connection cable from the on-site "
            f"substation to the connection point at [POC substation].\n"
            f"Work No. 5 — temporary construction compound(s), laydown areas, batching plant, "
            f"site cabins and welfare facilities.\n"
            f"Work No. 6 — landscaping, ecological mitigation planting, biodiversity net gain "
            f"habitat creation, drainage and SuDS features, fencing, gates and security CCTV. "
            f"({name})"
        )
    if tech == "bess":
        return (
            f"Work No. 1 — a battery energy storage system with up to {cap} MW / [MWh] nameplate "
            f"capacity, comprising containerised lithium-ion battery units, power conversion "
            f"systems, thermal management, fire-suppression systems and associated auxiliaries. "
            f"Work No. 2 — on-site substation and grid connection works. ({name})"
        )
    if tech == "dc":
        return (
            f"A Nationally Significant Infrastructure Project by direction under s.35 of the "
            f"2008 Act comprising: Work No. 1 — a data centre campus with up to {cap} MW IT "
            f"load including data halls, mechanical and electrical plant, cooling equipment, "
            f"emergency standby generators and fuel storage. Work No. 2 — on-site substation "
            f"and grid connection to [POC]. Work No. 3 — fibre connection and access routes. "
            f"({name})"
        )
    return f"[Authorised development — TO POPULATE per technology {tech}, capacity {cap} MW]"


def _requirements_schedule() -> str:
    return (
        "Requirements (conditions on development consent) include typically: "
        "R1 Time limits for commencement; R2 Detailed design approval; "
        "R3 Construction Environmental Management Plan (CEMP); "
        "R4 Landscape and Biodiversity Strategy; R5 Construction hours; "
        "R6 Lighting strategy; R7 Drainage strategy; R8 Archaeology WSI; "
        "R9 Noise limits (BS 4142); R10 Traffic management plan; "
        "R11 Decommissioning strategy (for generating stations, typically within 40 years); "
        "R12 Biodiversity net gain delivery plan (10% minimum per Environment Act 2021 s.98); "
        "R13 Glint and Glare assessment compliance (CAP 738, for solar); "
        "R14 Highway works approval; R15 Community benefit arrangements. "
        "[TO POPULATE individual requirement text at pre-submission.]"
    )


def _protective_provisions() -> str:
    return (
        "Protective provisions typically agreed with statutory undertakers and include: "
        "Part 1 — Electricity undertakers (National Grid Electricity Transmission, DNO); "
        "Part 2 — Gas undertakers; Part 3 — Water and sewerage undertakers; "
        "Part 4 — Electronic communications code operators; Part 5 — Highway authority; "
        "Part 6 — Lead local flood authority; Part 7 — Environment Agency. "
        "[TO POPULATE per Statement of Common Ground with each party.]"
    )


def _certified_documents_list() -> str:
    return (
        "Book of Reference; Design and Access Statement; Environmental Statement and appendices; "
        "Land Plans; Works Plans; Access and Rights of Way Plans; General Arrangement Plans; "
        "Landscape Masterplan; Outline CEMP; Outline Landscape and Biodiversity Strategy; "
        "Statement of Reasons; Funding Statement; Consultation Report."
    )
