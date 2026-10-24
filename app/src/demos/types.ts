export type ProductKey = "raw_value" | "residual_value" | "fitted_value";
export type DemoState = { view: "paired" | "radial"; selectedStationId: string; pinnedStationId: string | null; windowId: string; productKey: ProductKey };
export type Product = { key: ProductKey; label: string; units: string; available: boolean };
export type Source = { source_id: string; title: string; publisher: string; accessed_on: string; version_or_date: string; license_or_terms: string; processing_level: string; sha256: string; url: string | null };
export type StationMetadata = { station_id: string; source_id: string; station_type: "coastal" | "dart"; name: string; units: string; vertical_reference: string; horizontal_datum: string; coordinate_order: string; time_basis: string; latitude: number; longitude: number; observation_count: number; source: Source; products: Product[] };
export type DemoWindow = { id: string; label: string; start_utc?: string; end_utc_exclusive?: string };
export type Asset = { path: string; bytes: number; sha256: string };
export type DemoManifest = {
  schema_version: "1"; exporter_version: "1"; bundle_id: string; evidence_state: "internal_descriptive_only";
  event: { event_id: string; origin_time_utc: string; latitude: number; longitude: number };
  release: { release_id: string; arrival_comparison_allowed: false; physical_arrival_records_released: 0; continuous_nctr_field: "blocked_no_proxy"; allowed_uses: string[]; prohibited_uses: string[] };
  windows: DemoWindow[]; default_state: Omit<DemoState,"view">; stations: StationMetadata[]; assets: Asset[]; geometry_path: string;
  input_fingerprints: { path: string; sha256: string }[]; config_sha256: string;
  accounting: { source_observation_count: number; exported_observation_count: number; station_count: number; rejected_observation_count: number };
};
export type Observation = {
  observation_id: string; source_id: string; station_id: string; source_time: string; observed_at_utc: string;
  raw_value: number | null; fitted_value: number | null; residual_value: number | null; units: string; vertical_reference: string;
  raw_status: "observed" | "source_blank"; residual_status: "available" | "source_blank" | "structurally_not_applicable";
  grid_status: "on_grid" | "off_grid" | "not_applicable"; qc_flags: Record<string,string | number | boolean | null>;
  source_qc_status: "flagged" | "not_flagged" | "not_reported";
};
type SupportBase = { station_id: string; window_id: string; start_utc: string; end_utc_exclusive: string; accepted_sample_n: number; valid_sample_n: number; source_blank_n: number; product_valid_n: Record<ProductKey,number>; strict_numerator_n: number | null; strict_denominator_n: number | null; strict_percent: number | null };
export type CoastalSupport = SupportBase & {
  support_kind: "coastal_exact_grid"; expected_n: number | null; cadence_seconds: number | null; source_grid_anchor_utc: string;
  absent_n: number | null; off_grid_n: number | null; off_grid_valid_n: number | null; exact_valid_n: number | null;
  sample_density_numerator_n: number | null; sample_density_denominator_n: number | null; sample_density_percent: number | null;
  supported_start_utc: string; supported_end_utc_exclusive: string; first_grid_utc: string; last_grid_utc: string; first_valid_raw_utc: string; last_valid_raw_utc: string;
};
export type DartSupport = SupportBase & { support_kind: "dart_actual_timestamps"; strict_numerator_n: null; strict_denominator_n: null; strict_percent: null; cadence_seconds_counts: {seconds:number;count:number}[] };
export type Support = CoastalSupport | DartSupport;
export type CoverageSpan = { station_id: string; window_id: string; start_utc: string; end_utc_exclusive: string; status: string; absent_n: number; source_blank_n: number; affected_position_n: number; classification: string; classification_semantics: string; endpoint_semantics: string; left_observed_utc: string; right_observed_utc: string; within_block_valid_raw_n: number };
export type StationRecords = { schema_version: "1"; station_id: string; rows: Observation[]; support: Support[]; coverage_spans: CoverageSpan[]; gap_blocks: CoverageSpan[] };
export type DemoGeometry = { schema_version: "1"; source_crs: "EPSG:4326"; display_crs: string; coordinate_order: "x,y"; central_meridian: -160; coastline: number[][][]; points: {id:string;x:number;y:number}[]; bounds: [number,number,number,number] };
export type StationSelection = { station: StationMetadata; status: "loading" | "ready" | "error"; records: StationRecords | null; error: string | null };
export type RadialProps = {
  manifest: DemoManifest; geometry: DemoGeometry | null; geometryError: string | null; state: DemoState;
  selected: StationSelection; pinned: StationSelection | null;
  onSelectStation: (stationId:string)=>void; onOpenEvidence: (stationId:string)=>void;
  onRetryStation: (stationId:string)=>void; onRetryGeometry: ()=>void;
};
export type EvidenceProps = { manifest: DemoManifest; station: StationMetadata; records: StationRecords; windowId: string; productKey: ProductKey; onClose: ()=>void };
