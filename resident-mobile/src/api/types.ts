export type Identity = { id: string; email: string; role: 'resident' | 'admin' };
export type TokenResponse = { access_token: string; token_type: 'bearer'; expires_in: number };

export type View = 'side' | 'rear';
export type AnalysisStatus = 'pending' | 'processing' | 'failed' | 'complete';
export type AnalysisState = { status: AnalysisStatus; stage?: string | null };

export type SessionListItem = {
  session_id: string;
  session_label: string | null;
  recorded_at: string;
  analysis_status: AnalysisStatus;
  available_views: View[];
  plots_available: boolean;
  owner_user_id: string | null;
  owner_email?: string | null;
  resident_or_study_id: string | null;
};

export type MetricKey = 'neck_flexion_extension' | 'shoulder_hiking' | 'forward_trunk_lean' | 'lateral_trunk_lean';

export type ReferenceZoneExposure = {
  within_seconds: number | null;
  outside_seconds: number | null;
  within_percent: number | null;
  outside_percent: number | null;
  rule_label: string;
  rule_type: string;
  rule_explanation: string;
};

export type Category = {
  key: string;
  label: string;
  rula_score: number | null;
  rula_adjustment_present: boolean | null;
  seconds: number;
  percent_of_valid_time: number;
};

export type PostureSummary = {
  metric: MetricKey;
  label: string;
  view: View;
  unit: string;
  status: 'available' | 'unavailable' | 'insufficient_tracking';
  reason: string | null;
  valid_tracking_percent: number | null;
  reference_zone_exposure: ReferenceZoneExposure;
  category_distribution: Category[];
};

export type SessionDetail = {
  session_id: string;
  metadata: {
    session_label?: string | null;
    started_at?: string;
    ended_at?: string;
    created_at?: string;
    owner_user_id?: string;
  };
  analysis_status: AnalysisState;
  available_views: View[];
  posture_summaries: PostureSummary[];
  review_media_available: boolean;
};

export type TimePoint = {
  time_seconds: number;
  frame: number;
  category?: string | null;
  value?: number;
  posture_angle_deg?: number;
  right_value?: number | null;
  left_value?: number | null;
};

export type TimeSeries = {
  metric: MetricKey;
  label: string;
  view: View;
  unit: string;
  status: 'available' | 'insufficient_tracking';
  reason: string | null;
  source_point_count: number;
  returned_point_count: number;
  downsampled: boolean;
  max_points: number;
  points: TimePoint[];
};
