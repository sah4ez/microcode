// Package dto holds the request/response types for the todo service contract.
// These types are referenced from the @tg contract in contracts/todo.go as
// dto.Type and are resolved by the astg plugin via go/types.
package dto

// Todo is a single stored todo item.
//
// @tg desc=`A single todo item`
type Todo struct {
	// ID is the unique, server-assigned identifier.
	// @tg desc=`Unique todo identifier`
	ID int64 `json:"id"`

	// LkID is the личный кабинет (personal profile) this todo belongs to. It is
	// supplied by the client on create via the `x-lk-id` request header and used
	// to scope list/get so a request only ever sees its own cabinet's records.
	// @tg desc=`Personal profile (cabinet) id this todo belongs to`
	LkID int64 `json:"lk_id"`

	// Title is the short summary. Required on create.
	// @tg desc=`Short summary of the todo`
	Title string `json:"title"`

	// Description is the optional long-form body.
	// @tg desc=`Long-form description`
	Description string `json:"description"`

	// Completed reports whether the todo is done.
	// @tg desc=`Whether the todo is completed`
	Completed bool `json:"completed"`

	// CreatedAt is the RFC3339 (UTC) creation timestamp.
	// @tg desc=`Creation timestamp (RFC3339, UTC)`
	CreatedAt string `json:"created_at"`
}
