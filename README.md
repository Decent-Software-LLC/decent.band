# decent.band

The interactive artist-hometown map for [decent.band](https://decent.band).

The `dev` branch is published at [dev.decent.band](https://dev.decent.band).
It uses Vite, MapLibre GL, and the Billboard Global 200 artist datasets in
`public/data/billboard-global-200-2023-2026/`. The published directory merges
the complete performer metadata with the top-300 chart details and removes
duplicate artist-name variants before mapping hometowns.

Run `npm install` and `npm run dev` for local development. Run `npm run build`
to create the production bundle in `dist/`.
