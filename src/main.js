import { Map, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";

setWorkerUrl(workerUrl);

const SOURCE_ID = "artists";
const INITIAL_VIEW = { center: [8, 18], zoom: 1.35, pitch: 0, bearing: 0 };
const mapStyle = import.meta.env.VITE_MAP_STYLE_URL || "https://tiles.openfreemap.org/styles/liberty";
const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let spinFrame;
let previousSpinTime;
let spinEnabled = !prefersReducedMotion;
let artistDirectory = [];

const mapStatus = document.querySelector("#map-status");
const artistCount = document.querySelector("#artist-count");
const intro = document.querySelector("#map-intro");
const mapElement = document.querySelector("#map");
const listView = document.querySelector("#list-view");
const listContainer = document.querySelector("#artist-directory");
const sortSelect = document.querySelector("#artist-sort");
const mapViewButton = document.querySelector("#map-view-button");
const listViewButton = document.querySelector("#list-view-button");
const resetViewButton = document.querySelector("#reset-view");

const map = new Map({
  container: "map",
  style: mapStyle,
  ...INITIAL_VIEW,
  attributionControl: true,
  cooperativeGestures: true,
  maxPitch: 70,
});

map.addControl(new NavigationControl({ showCompass: true, visualizePitch: true }), "bottom-right");

map.on("style.load", () => {
  map.setProjection({ type: "globe" });
  map.setSky({
    "sky-color": "#1b1b1d",
    "horizon-color": "#1b1b1d",
    "fog-color": "#1b1b1d",
    "sky-horizon-blend": 0.08,
    "horizon-fog-blend": 0.08,
    "fog-ground-blend": 0.12,
  });

  for (const layer of map.getStyle().layers || []) {
    const isMapLabel = layer.type === "symbol";
    const isAdministrativeBorder =
      layer.type === "line" && /admin|boundary|border/i.test(layer.id);

    if (isMapLabel || isAdministrativeBorder) {
      map.setLayoutProperty(layer.id, "visibility", "none");
    }
  }
});

map.on("load", async () => {
  try {
    const response = await fetch("/data/artists.geojson");
    if (!response.ok) throw new Error(`Artist data returned ${response.status}`);

    const geojson = await response.json();
    const totalArtists = geojson.metadata?.artistCount ??
      geojson.features.reduce((sum, feature) => sum + Number(feature.properties.artistCount || 0), 0);
    artistCount.textContent = `${totalArtists} artists · ${geojson.features.length} hometowns`;
    artistDirectory = geojson.features.flatMap((feature) =>
      parseArtists(feature.properties.artists).map((artist) => ({
        ...artist,
        hometown: feature.properties.hometown,
      })),
    );
    document.querySelector("#list-summary").textContent =
      `${totalArtists} artists from ${geojson.features.length} hometowns`;
    renderArtistDirectory();

    map.addSource(SOURCE_ID, {
      type: "geojson",
      data: geojson,
      cluster: true,
      clusterMaxZoom: 8,
      clusterRadius: 48,
      clusterProperties: {
        artist_count_sum: ["+", ["get", "artistCount"]],
      },
    });

    map.addLayer({
      id: "artist-clusters",
      type: "circle",
      source: SOURCE_ID,
      filter: ["has", "point_count"],
      paint: {
        "circle-color": ["step", ["get", "artist_count_sum"], "#8fbcff", 30, "#5a9bfa", 75, "#3b86f6"],
        "circle-radius": ["step", ["get", "artist_count_sum"], 20, 30, 27, 75, 34],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
        "circle-opacity": 0.95,
      },
    });

    map.addLayer({
      id: "artist-cluster-count",
      type: "symbol",
      source: SOURCE_ID,
      filter: ["has", "point_count"],
      layout: { "text-field": ["get", "artist_count_sum"], "text-size": 13 },
      paint: { "text-color": "#231f20" },
    });

    map.addLayer({
      id: "artist-pins",
      type: "circle",
      source: SOURCE_ID,
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": "#3b86f6",
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["get", "artistCount"],
          1,
          6,
          5,
          10,
          20,
          15,
        ],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });

    mapStatus.hidden = true;
    startGlobeSpin();
  } catch (error) {
    console.error(error);
    mapStatus.textContent = "Artist data could not be loaded. Please try again.";
    mapStatus.classList.add("map-status--error");
  }
});

for (const eventName of ["mousedown", "touchstart", "wheel"]) {
  map.on(eventName, stopGlobeSpin);
}

map.on("click", "artist-clusters", async (event) => {
  const feature = map.queryRenderedFeatures(event.point, { layers: ["artist-clusters"] })[0];
  if (!feature) return;
  const source = map.getSource(SOURCE_ID);
  const zoom = await source.getClusterExpansionZoom(feature.properties.cluster_id);
  map.easeTo({ center: feature.geometry.coordinates, zoom });
});

map.on("click", "artist-pins", (event) => {
  const feature = event.features?.[0];
  if (!feature) return;
  const properties = feature.properties;
  const artists = parseArtists(properties.artists);

  new Popup({
    anchor: "bottom",
    offset: 14,
    maxWidth: "440px",
    className: "artist-map-popup",
  })
    .setLngLat(feature.geometry.coordinates)
    .setDOMContent(buildArtistPopup(properties.hometown, artists))
    .addTo(map);

  map.easeTo({
    center: feature.geometry.coordinates,
    offset: [0, window.innerWidth <= 760 ? 120 : 165],
    duration: prefersReducedMotion ? 0 : 450,
  });
});

for (const layer of ["artist-clusters", "artist-pins"]) {
  map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
}

map.on("error", (event) => {
  if (!map.loaded()) {
    mapStatus.textContent = "The map could not be loaded. Please try again.";
    mapStatus.classList.add("map-status--error");
  }
  console.error(event.error);
});

resetViewButton.addEventListener("click", () => {
  stopGlobeSpin();
  spinEnabled = !prefersReducedMotion;
  previousSpinTime = undefined;
  map.flyTo({ ...INITIAL_VIEW, duration: 1200 });
  map.once("moveend", startGlobeSpin);
});

mapViewButton.addEventListener("click", () => setView("map"));
listViewButton.addEventListener("click", () => setView("list"));
sortSelect.addEventListener("change", renderArtistDirectory);

document.querySelector("#dismiss-intro").addEventListener("click", () => {
  intro.hidden = true;
  map.getCanvas().focus();
});

function buildArtistPopup(hometown, artists) {
  const popup = document.createElement("article");
  popup.className = "artist-popup";

  const heading = document.createElement("h2");
  heading.textContent = hometown;
  popup.append(heading);

  const summary = document.createElement("p");
  summary.className = "artist-popup__summary";
  summary.textContent = `${artists.length} ${artists.length === 1 ? "artist" : "artists"} from this hometown`;
  popup.append(summary);

  const list = document.createElement("div");
  list.className = "artist-popup__list";
  list.tabIndex = 0;
  list.setAttribute("aria-label", `Scrollable list of artists from ${hometown}`);

  for (const artist of artists) {
    const card = document.createElement("section");
    card.className = "artist-card";

    const rank = document.createElement("p");
    rank.className = "artist-card__rank";
    rank.textContent = `Global rank ${artist.rank}`;
    card.append(rank);

    const name = document.createElement("h3");
    name.textContent = artist.name;
    card.append(name);

    const genre = document.createElement("p");
    genre.className = "artist-card__genre";
    genre.textContent = artist.genre;
    card.append(genre);

    const notes = document.createElement("p");
    notes.className = "artist-card__notes";
    notes.textContent = artist.notes;
    card.append(notes);

    const details = document.createElement("dl");
    addDetail(details, "Peak", `#${artist.peakPosition}`);
    addDetail(details, "Songs", artist.chartedSongs.toLocaleString());
    addDetail(details, "Weeks", artist.weeksCharted.toLocaleString());
    card.append(details);
    list.append(card);
  }

  popup.append(list);
  return popup;
}

function setView(view) {
  const showList = view === "list";
  listView.hidden = !showList;
  mapElement.hidden = showList;
  intro.hidden = true;
  mapViewButton.classList.toggle("is-active", !showList);
  listViewButton.classList.toggle("is-active", showList);
  mapViewButton.setAttribute("aria-pressed", String(!showList));
  listViewButton.setAttribute("aria-pressed", String(showList));
  resetViewButton.hidden = showList;

  if (showList) {
    stopGlobeSpin();
    listView.querySelector("h1").focus({ preventScroll: true });
  } else {
    map.resize();
    spinEnabled = !prefersReducedMotion;
    previousSpinTime = undefined;
    startGlobeSpin();
    map.getCanvas().focus();
  }
}

function renderArtistDirectory() {
  const sortBy = sortSelect.value;
  const sortedArtists = [...artistDirectory].sort((a, b) => {
    const values = {
      artist: [a.name, b.name],
      genre: [a.genre, b.genre],
      location: [a.hometown, b.hometown],
    }[sortBy];
    return values[0].localeCompare(values[1], undefined, { sensitivity: "base" }) ||
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  });

  listContainer.replaceChildren(...sortedArtists.map(buildDirectoryRow));
}

function buildDirectoryRow(artist) {
  const article = document.createElement("article");
  article.className = "directory-row";

  const rank = document.createElement("span");
  rank.className = "directory-row__rank";
  rank.textContent = String(artist.rank).padStart(3, "0");

  const identity = document.createElement("div");
  identity.className = "directory-row__identity";
  const name = document.createElement("h2");
  name.textContent = artist.name;
  const notes = document.createElement("p");
  notes.textContent = artist.notes;
  identity.append(name, notes);

  const genre = buildDirectoryField("Genre", artist.genre);
  const location = buildDirectoryField("Hometown", artist.hometown);
  article.append(rank, identity, genre, location);
  return article;
}

function buildDirectoryField(label, value) {
  const field = document.createElement("div");
  field.className = "directory-row__field";
  const heading = document.createElement("span");
  heading.textContent = label;
  const content = document.createElement("p");
  content.textContent = value;
  field.append(heading, content);
  return field;
}

function parseArtists(value) {
  if (Array.isArray(value)) return value;
  try {
    return JSON.parse(value || "[]");
  } catch {
    return [];
  }
}

function addDetail(list, term, value) {
  const wrapper = document.createElement("div");
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  wrapper.append(dt, dd);
  list.append(wrapper);
}

function startGlobeSpin() {
  if (!spinEnabled || spinFrame) return;

  const spin = (time) => {
    if (!spinEnabled) {
      spinFrame = undefined;
      return;
    }

    if (previousSpinTime !== undefined) {
      const elapsedSeconds = Math.min((time - previousSpinTime) / 1000, 0.1);
      const center = map.getCenter();
      map.setCenter([center.lng + elapsedSeconds * 1.25, center.lat]);
    }

    previousSpinTime = time;
    spinFrame = window.requestAnimationFrame(spin);
  };

  spinFrame = window.requestAnimationFrame(spin);
}

function stopGlobeSpin() {
  spinEnabled = false;
  previousSpinTime = undefined;
  if (spinFrame) window.cancelAnimationFrame(spinFrame);
  spinFrame = undefined;
}
