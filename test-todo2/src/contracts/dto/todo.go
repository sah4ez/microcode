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
