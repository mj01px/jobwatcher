"""Seed the default highlight keywords and the initial monitored companies.

Values are frozen here on purpose: later edits to application constants must
never change what this migration inserted.
"""

from __future__ import annotations

from django.db import migrations
from django.utils import timezone

DEFAULT_KEYWORDS = [
    "ai",
    "android",
    "artificial intelligence",
    "backend",
    "back-end",
    "developer",
    "desenvolvedor",
    "desenvolvedora",
    "engineering lead",
    "flutter",
    "frontend",
    "front-end",
    "full stack",
    "fullstack",
    "inteligência artificial",
    "java",
    "javascript",
    "kotlin",
    "machine learning",
    "mobile",
    "node",
    "python",
    "react",
    "react native",
    "software engineer",
    "tech lead",
    "technical lead",
    "typescript",
]

SEED_COMPANIES = [
    ("dti digital", "https://dtidigital.inhire.app/vagas"),
    ("VR", "https://vr.inhire.app/vagas"),
    ("Lyncas", "https://lyncas.inhire.app/vagas"),
    ("Icon", "https://iconit.inhire.app/vagas"),
    ("Azos", "https://azos.inhire.app/vagas"),
    ("Programmers", "https://programmers.inhire.app/vagas"),
    ("Atlas Technologies", "https://atlastechnol.inhire.app/vagas"),
    ("Sevenred", "https://sevenred.inhire.app/vagas"),
    ("Nomad", "https://nomadglobal.inhire.app/vagas"),
    ("Pantheon Inc", "https://pantheon.inhire.app/vagas"),
    ("LWSA / Octadesk", "https://lwsa.inhire.app/octadesk/vagas"),
    ("Growdev", "https://growdev.inhire.app/vagas"),
    ("Pitang", "https://pitang.inhire.app/vagas"),
    ("Framework Digital", "https://frameworkdigital.inhire.app/vagas"),
    ("Radix", "https://radix.inhire.app/vagas"),
    ("ed", "https://somosed.inhire.app/vagas"),
    ("Premiersoft", "https://premiersoft.inhire.app/vagas"),
    ("Platform Builders", "https://platformbuilders.inhire.app/vagas"),
    ("CSP Tech", "https://csptech.inhire.app/vagas"),
    ("Upda", "https://upda.inhire.app/vagas"),
    ("Dataside", "https://dataside.inhire.app/vagas"),
    ("2biz Company", "https://2bizcompany.inhire.app/vagas"),
    ("Superlógica Tecnologias", "https://superlogica.inhire.app/vagas"),
    ("Brivia", "https://brivia.inhire.app/vagas"),
    ("Venturus", "https://venturus.inhire.app/vagas"),
    ("Mazzatech", "https://mazzatech.inhire.app/vagas"),
    ("minu.co", "https://minu.inhire.app/vagas"),
    ("Kooper / Supero", "https://kooperecooperativa.inhire.app/supero/vagas"),
    ("Remessa Online", "https://remessaonline.inhire.app/vagas"),
    ("VONBZ", "https://vonbz.inhire.app/vagas"),
    ("Alice", "https://alice.inhire.app/vagas"),
    ("Vagas by Intera", "https://vagasbyintera.inhire.app/vagas"),
    ("Portal", "https://portal.inhire.app/vagas"),
    ("Livemode", "https://livemode.inhire.app/vagas"),
    ("Global System", "https://globalsystem.inhire.app/vagas"),
    ("CashMe", "https://cashme.inhire.app/vagas"),
    ("MB Labs", "https://mblabs.inhire.app/vagas"),
    ("Olist", "https://olist.inhire.app/vagas"),
    ("MJV", "https://mjv.inhire.app/vagas"),
    ("Zallpy", "https://zallpy.inhire.app/vagas"),
    ("BRQ", "https://brq.inhire.app/vagas"),
    ("PX Center", "https://pxcenter.inhire.app/vagas"),
    ("Vórtx", "https://vortx.inhire.app/vagas"),
    ("e-Core", "https://ecore.inhire.app/vagas"),
    ("Tech6 Group", "https://tech6group.inhire.app/vagas"),
    ("Share People Hub", "https://sharepeoplehub.inhire.app/vagas"),
    ("Hand", "https://hand.inhire.app/vagas"),
    ("Deal", "https://deal.inhire.app/vagas"),
    ("Tinnova", "https://tinnova.inhire.app/vagas"),
    ("Tera", "https://tera.inhire.app/vagas"),
    ("Cora", "https://cora.inhire.app/vagas"),
    ("Intera", "https://intera.inhire.app/vagas"),
    ("Sanar", "https://sanar.inhire.app/vagas"),
    ("Raro Labs", "https://rarolabs.inhire.app/vagas"),
    ("Cubos", "https://cubos.inhire.app/vagas"),
    ("Octafy", "https://octafy.inhire.app/vagas"),
    ("Qive", "https://qive.inhire.app/vagas"),
    ("DB1", "https://db1.inhire.app/vagas"),
    ("Cardápio Web", "https://cardapioweb.inhire.app/vagas"),
    ("Housi", "https://housi.inhire.app/vagas"),
    ("Grupo Taking", "https://grupotaking.inhire.app/vagas"),
    ("Dot Group", "https://dotgroup.inhire.app/vagas"),
    ("RPO XP Inc", "https://rpo-xpinc.inhire.app/vagas"),
    ("Grupo GCB Investimentos", "https://grupogcbinvestimentos.inhire.app/vagas"),
    ("Frete.com", "https://frete.inhire.app/vagas"),
    ("Cielo", "https://cielo.inhire.app/tecnologia/vagas"),
    ("Magazord", "https://magazord.inhire.app/vagas"),
    ("Inbazz", "https://inbazz.inhire.app/vagas"),
    ("Kobe Apps", "https://kobe.inhire.app/vagas"),
    ("Toro Investimentos", "https://toroinvestimentos.inhire.app/vagas"),
    ("Atlântico", "https://atlantico.inhire.app/vagas"),
    ("Auvo Tecnologia", "https://auvotecnologia.inhire.app/vagas"),
    ("Pris", "https://pris.inhire.app/vagas"),
    ("Bix Tecnologia", "https://bixtecnologia.inhire.app/vagas"),
]


def seed(apps, schema_editor):
    Company = apps.get_model("watcher", "Company")
    Setting = apps.get_model("watcher", "Setting")
    now = timezone.now()
    Setting.objects.get_or_create(
        key="highlight_keywords",
        defaults={"value": DEFAULT_KEYWORDS, "updated_at": now},
    )
    existing = set(Company.objects.values_list("url", flat=True))
    Company.objects.bulk_create(
        Company(name=name, url=url, created_at=now, updated_at=now)
        for name, url in SEED_COMPANIES
        if url not in existing
    )


class Migration(migrations.Migration):
    dependencies = [("watcher", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
