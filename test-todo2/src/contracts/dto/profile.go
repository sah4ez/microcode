package dto

// PersonalProfile is a личный кабинет (personal cabinet/profile). Todos are
// partitioned by LkID so a request carrying a given `x-lk-id` only ever sees
// the todos that belong to that cabinet. Example cabinets: "работа" (work) and
// "дом" (home), each holding its own independent todo list.
//
// @tg desc=`A personal cabinet (ЛК) that owns a set of todos`
type PersonalProfile struct {
	// ID is the unique, server-assigned identifier used as `x-lk-id` on todo
	// requests.
	// @tg desc=`Unique personal profile (cabinet) identifier`
	ID int64 `json:"id"`

	// Name is the human-readable cabinet name (e.g. "работа", "дом").
	// @tg desc=`Cabinet name`
	Name string `json:"name"`

	// CreatedAt is the RFC3339 (UTC) creation timestamp.
	// @tg desc=`Creation timestamp (RFC3339, UTC)`
	CreatedAt string `json:"created_at"`
}