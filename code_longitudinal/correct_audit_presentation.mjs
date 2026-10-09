import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const ROOT = "C:/Users/pierr/Desktop/ARECode/ARE/part2/longitudinal_2022";
const SKILL_DIR = "C:/Users/pierr/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations";
const RUNTIME_PYTHON = "C:/Users/pierr/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const SOURCE = path.join(ROOT, "work/longitudinal_2000_v1_full_240_professeur_candidate/04_PRESENTATION/PRESENTATION_RESULTATS_240.pptx");
const BUILD = path.join(ROOT, "work/presentation_correction_audit");
const FINAL = path.join(ROOT, "deliverables/CORRECTION_AUDIT_20260908/PRESENTATION_RESULTATS_240_CORRIGEE_v2.pptx");
const FIGURES = path.join(ROOT, "work/longitudinal_2000_release_professeur_candidate/03_FIGURES");

function shapeByName(slide, name) {
  const result = slide.shapes.items.find((item) => item.name === name);
  if (!result) throw new Error(`Missing shape ${name}`);
  return result;
}

function imageByName(slide, name) {
  const result = slide.images.items.find((item) => item.name === name);
  if (!result) throw new Error(`Missing image ${name}`);
  return result;
}

function replaceExact(slide, name, oldText, newText) {
  shapeByName(slide, name).text.replace(oldText, newText);
}

async function imageBuffer(source) {
  const bytes = await fs.readFile(source);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

async function replaceImage(slide, name, source, alt) {
  const current = imageByName(slide, name);
  const position = {
    left: current.position.left,
    top: current.position.top,
    width: current.position.width,
    height: current.position.height,
  };
  current.delete();
  const replacement = slide.images.add({
    blob: await imageBuffer(source),
    contentType: "image/png",
    alt,
    fit: "contain",
    position,
  });
  replacement.name = name;
}

async function renderAndInspect(presentation) {
  const renderDir = path.join(BUILD, "final-render");
  const layoutDir = path.join(BUILD, "final-layout");
  await fs.mkdir(renderDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });
  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const image = await presentation.export({ slide, format: "png", scale: 1 });
    await fs.writeFile(path.join(renderDir, `${stem}.png`), new Uint8Array(await image.arrayBuffer()));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(layoutDir, `${stem}.layout.json`), await layout.text(), "utf8");
  }
  const montage = await presentation.export({ format: "webp", montage: true, scale: 1 });
  await fs.writeFile(path.join(BUILD, "final-montage.webp"), new Uint8Array(await montage.arrayBuffer()));
  const inspect = await presentation.inspect({ kind: "slide,textbox,shape,image,chart,table,notes,layout", maxChars: 180000 });
  await fs.writeFile(path.join(BUILD, "final.inspect.ndjson"), inspect.ndjson, "utf8");
}

async function main() {
  await fs.mkdir(BUILD, { recursive: true });
  const presentation = await PresentationFile.importPptx(await FileBlob.load(SOURCE));
  if (presentation.slides.items.length !== 20) throw new Error("Expected 20 slides");

  const s2 = presentation.slides.getItem(1);
  for (const [name, value] of [["metric-label-KRT canoniques", "KRT calculés"], ["metric-label-R EI valides", "R EI calculés"]]) {
    const label = shapeByName(s2, name);
    label.text = value;
    label.text.typeface = "Arial";
    label.text.fontSize = 16;
    label.text.color = "#20242A";
  }

  const s3 = presentation.slides.getItem(2);
  replaceExact(s3, "method-body-1", "Bêta-binomial NumPyro · β communaux · intervalles postérieurs", "KRT Python · backend PyMC ou NumPyro selon le run · intervalles postérieurs");
  replaceExact(s3, "footer-source", "Sources : panel_2000.csv, MODEL_SCENARIOS.csv et tables principales.", "Sources : panel_2000.csv, MODEL_SCENARIOS.csv et diagnostics_KRT_runs.csv.");

  const central = [
    { slide: 4, scenario: "H0A", family: "legislative", takeaway: ["Négatif au début, positif depuis les années 1980.", "Transformation de signe, sans rupture uniforme entre méthodes ou scrutins."], details: ["• Pic au début des années 2000\n\n• KRT et R EI suivent la même forme\n\n• Intervalle et diagnostic restent attachés", "• 1962 : −12,0 points [−15,0 ; −8,9]\n\n• 2022 : +9,0 points [6,8 ; 11,2]\n\n• Caveat ouvert ; fail gris et ligne interrompue"] },
    { slide: 5, scenario: "H0A", family: "presidential", takeaway: ["Le contraste récent est positif, mais moins élevé qu'aux législatives.", "La transformation apparaît aussi aux présidentielles, selon un calendrier propre."], details: ["• Bascule plus progressive\n\n• Écart KRT–R limité\n\n• Scrutins séparés pour éviter une moyenne trompeuse", "• 2022 : +7,0 points [5,3 ; 8,5]\n\n• Ne pas moyenner avec les législatives\n\n• Comparaison de méthodes = sensibilité, pas identité"] },
    { slide: 6, scenario: "H1", family: "legislative", takeaway: ["Positif pendant une grande partie de la période, négatif en 2022.", "Transformation de long terme ; le point de départ 1962 reste incertain."], details: ["• Sommet autour des années 1980\n\n• Déclin après 2000\n\n• Concordance de signe KRT–R en 2022", "• 1962 : +4,5 points [−2,9 ; 11,5]\n\n• 1986 : +13,8 points [8,4 ; 18,8]\n\n• 2022 : −5,5 points [−8,8 ; −2,0]"] },
    { slide: 7, scenario: "H1", family: "presidential", takeaway: ["Le contraste atteint un maximum à la fin des années 1980 puis passe sous zéro.", "La série récente devient négative, avec prudence particulière pour 2012 et 2017."], details: ["• Convergence vers zéro après 2000\n\n• Négatif en 2022\n\n• Association écologique, non transfert individuel", "• 2022 : −4,1 points [−6,4 ; −1,8]\n\n• 2012/2017 : lecture diagnostique prudente\n\n• Association écologique, non transfert individuel"] },
  ];
  for (const item of central) {
    const slide = presentation.slides.getItem(item.slide - 1);
    replaceExact(slide, `takeaway-${item.slide}`, item.takeaway[0], item.takeaway[1]);
    const detailShape = shapeByName(slide, `details-${item.slide}`);
    detailShape.text = item.details[1];
    detailShape.text.typeface = "Arial";
    detailShape.text.fontSize = 16.2;
    detailShape.text.color = "#20242A";
    await replaceImage(slide, "Picture 18", path.join(FIGURES, `trajectoire_${item.scenario}/${item.scenario}_${item.family}.png`), `${item.scenario} — ${item.family}, statuts numériques visibles`);
  }

  const extensions = [
    [8, "H0B", "Extension : 0 pass, 23 caveat et 3 fail. Lecture descriptive uniquement."],
    [9, "H0C", "Extension : 0 pass, 7 caveat et 19 fail. Aucune conclusion générale."],
    [10, "H2", "Extension : 3 pass, 13 caveat et 10 fail. Résultat très conditionnel."],
    [11, "H3", "Série non validée : 0 pass, 2 caveat et 24 fail."],
    [12, "H4", "Extension : 5 pass, 6 caveat et 15 fail. Interprétation limitée."],
    [13, "H5", "Aucun couple KRT validé : 0 pass et 26 fail. Pas de conclusion substantielle."],
    [14, "H6", "Extension depuis 1986 : 0 pass, 13 caveat et 3 fail."],
    [15, "H7", "Extension depuis 1986 : 0 pass, 5 caveat et 11 fail."],
  ];
  for (const [slideNumber, scenario, takeaway] of extensions) {
    const slide = presentation.slides.getItem(slideNumber - 1);
    const takeawayShape = shapeByName(slide, "takeaway-8");
    takeawayShape.text = takeaway;
    takeawayShape.text.typeface = "Arial";
    takeawayShape.text.fontSize = 18;
    takeawayShape.text.color = "#20242A";
    const details = shapeByName(slide, "details-8");
    details.text = "• Analyse secondaire\n\n• Plein = pass ; ouvert = caveat\n\n• Gris × = fail ; ligne interrompue";
    details.text.typeface = "Arial";
    details.text.fontSize = 16.2;
    details.text.color = "#20242A";
    await replaceImage(slide, `trajectory-${scenario}`, path.join(FIGURES, `trajectoires_KRT_R_NLS_toutes_hypotheses/combined/${scenario}_legislative_presidential.png`), `${scenario} — extension diagnostique, statuts visibles`);
  }

  const s16 = presentation.slides.getItem(15);
  replaceExact(s16, "title-10", "KRT et NLS s'alignent globalement, avec des exceptions", "KRT–NLS : une sensibilité, pas une validation croisée");
  replaceExact(s16, "takeaway-10", "La plupart des 240 couples restent proches de la diagonale.", "La diagonale indique l'égalité numérique ; elle ne prouve ni convergence ni identification.");
  const s16Details = shapeByName(s16, "details-10");
  s16Details.text = "• Plein = pass\n\n• Ouvert = caveat / warning\n\n• Gris × = au moins un fail";
  s16Details.text.typeface = "Arial";
  s16Details.text.fontSize = 16.2;
  s16Details.text.color = "#20242A";
  await replaceImage(s16, "Picture 18", path.join(FIGURES, "comparaison_KRT_NLS/comparaison_krt_nls.png"), "Comparaison diagnostique KRT–NLS");

  const s17 = presentation.slides.getItem(16);
  replaceExact(s17, "takeaway-11", "H3 présente l'écart absolu médian le plus élevé ; H0B le plus faible.", "Les écarts entre KRT et R mesurent une sensibilité de modèle, pas une robustesse substantielle.");
  const s17Details = shapeByName(s17, "details-11");
  s17Details.text = "• R EI n'est pas le même modèle que KRT\n\n• H3/H5 ne portent pas de conclusion validée\n\n• Les 240 couples restent auditables";
  s17Details.text.typeface = "Arial";
  s17Details.text.fontSize = 16.2;
  s17Details.text.color = "#20242A";

  const s18 = presentation.slides.getItem(17);
  replaceExact(s18, "title-12", "Chaque commune compte une fois dans le plan β₁–β₂", "Moyennes communales estimées dans le plan β₁–β₂");
  replaceExact(s18, "distribution-subtitle", "Quatre panneaux : H0A/H1 × législatives/présidentielles. La diagonale repère β₁=β₂.", "Quatre panneaux H0A/H1 × scrutin. Ni individus observés ni distribution postérieure nationale ; diagonale : β₁=β₂.");
  replaceExact(s18, "footer-source", "Source : 03_FIGURES/distributions_2D_2022/distributions_2d_2022.png ; 4 000 communes-panneaux par hypothèse.", "Source : 03_FIGURES/distributions_2D_2022/distributions_2d_2022.png ; moyennes postérieures communales estimées.");
  await replaceImage(s18, "Picture 14", path.join(FIGURES, "distributions_2D_2022/distributions_2d_2022.png"), "Distribution des moyennes communales estimées en 2022");

  const s19 = presentation.slides.getItem(18);
  replaceExact(s19, "diag-callout-text", "Les relances diagnostiques ciblées ne sont pas sélectionnées. Les statuts caveat/fail restent visibles dans les Parquet et les diagnostics résumés.", "Sélection exacte : 52 canonical_v1.0.2 + 188 initial_fit_user_selected. Backends : 145 PyMC + 95 NumPyro. Six runs H0A/H1 sont renforcés à 2 000/2 000.");
  replaceExact(s19, "footer-source", "Sources : diagnostics_KRT_resume.csv, diagnostics_NLS_resume.csv, identification_resume.csv.", "Sources : diagnostics_KRT_par_hypothese.csv, diagnostics_KRT_runs.csv et diagnostics_NLS_resume.csv.");

  const s20 = presentation.slides.getItem(19);
  replaceExact(s20, "conclusion-result", "H0A et H1 dessinent deux recompositions temporelles robustes descriptivement.", "H0A et H1 décrivent deux transformations temporelles écologiques, avec diagnostics attachés.");
  const deliveryList = shapeByName(s20, "delivery-list");
  deliveryList.text = "• H0A/H1 centraux\n\n• Extensions clairement séparées\n\n• Rapport HTML + PDF\n\n• Tables Parquet + diagnostics\n\n• ZIP professeur et technique\n\n• Guide slide par slide";
  deliveryList.text.typeface = "Arial";
  deliveryList.text.fontSize = 18;
  deliveryList.text.color = "#20242A";
  replaceExact(s20, "next-step", "Prochaine extension : modèle 3×2 et covariables, avec nouvelle stratégie d'identification.", "Statuts séparés : couverture, intégrité, validation numérique et périmètre scientifique.");
  replaceExact(s20, "footer-source", "Politique de sélection : initial_only · couverture : Python 240/240 · R 240/240.", "Sélection : 52 canonical_v1.0.2 + 188 initial_fit_user_selected · couverture : KRT 240/240 · R 240/240.");

  const sourceSha256 = crypto.createHash("sha256").update(await fs.readFile(SOURCE)).digest("hex");
  const requirements = {
    explicitTotalSlideCount: 20,
    requiredNativeTableOwnerSlides: [],
    requiredNativeChartOwnerSlides: [],
    requiredEmbeddedWorkbookChartOwnerSlides: [],
    sourceTemplatePath: SOURCE,
  };
  const fontPolicy = { basis: "reference", families: ["Arial"], referencePath: SOURCE, referenceSha256: sourceSha256 };
  const expectedSlideSizeEmu = "12192000,6858000";
  const { finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);
  const stagingDir = path.join(BUILD, ".codex-finalizer");
  await fs.mkdir(stagingDir, { recursive: true });
  await fs.mkdir(path.dirname(FINAL), { recursive: true });
  const candidatePath = path.join(stagingDir, "candidate.pptx");
  await (await PresentationFile.exportPptx(presentation)).save(candidatePath);
  const result = await finalizePresentation({
    ...requirements,
    workspaceDir: ROOT,
    candidatePath,
    finalPath: FINAL,
    pythonExecutable: RUNTIME_PYTHON,
    integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
    layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
    layoutArgs: ["--expected-slide-size-emu", expectedSlideSizeEmu, "--validate-bullet-geometry", "--validate-heading-fit"],
    requiredNativeTableOwnerSlides: [],
    fontPolicy,
    verifyArtifactToolImport: true,
    receiptPath: path.join(stagingDir, "PRESENTATION_RESULTATS_240_CORRIGEE_v2.validation.json"),
  });
  const finalPresentation = await PresentationFile.importPptx(await FileBlob.load(FINAL));
  await renderAndInspect(finalPresentation);
  console.log(JSON.stringify({ status: "complete", final: FINAL, validation: result, slides: 20 }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
