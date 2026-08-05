// Package contracts declares the todo service API as a @tg-annotated Go
// interface. The HTTP (fiber) transport is GENERATED from this contract by
// `tg server -o internal/transport`; business logic lives in internal/service.
package contracts

import (
	"context"

	"github.com/loki/todoservice/contracts/dto"
)

// @tg title=`Todo Service`
// @tg version=`1.0.0`
// @tg desc=`A minimal todo-list REST API persisted to SQLite.`
// @tg http-server
// @tg metrics
type TodoService interface {
	// Create stores a new todo in the cabinet identified by the `x-lk-id`
	// request header and returns it with id/created_at/completed=false.
	//
	// @tg http-method=POST
	// @tg http-path=`/todos`
	// @tg http-success=201
	// @tg enableInlineSingle
	// @tg http-headers=lkId|x-lk-id|explicit
	// @tg summary=`Create a todo`
	// @tg requestBodyDesc=`Title is required; description is optional.`
	// @tg lkId.desc=`Cabinet id, supplied via the x-lk-id header`
	// @tg lkId.required
	// @tg title.required
	// @tg title.desc=`Short summary, must be non-empty`
	// @tg description.desc=`Optional long-form description`
	Create(ctx context.Context, lkId int64, title string, description string) (todo dto.Todo, err error)

	// List returns every todo that belongs to the cabinet identified by the
	// `x-lk-id` request header (only that cabinet's records are returned).
	//
	// @tg http-method=GET
	// @tg http-path=`/todos`
	// @tg http-headers=lkId|x-lk-id|explicit
	// @tg summary=`List todos for the active cabinet`
	// @tg lkId.desc=`Cabinet id, supplied via the x-lk-id header`
	// @tg lkId.required
	List(ctx context.Context, lkId int64) (todos []dto.Todo, err error)

	// Get returns a single todo by id, but only if it belongs to the cabinet
	// identified by the `x-lk-id` request header; otherwise ErrNotFound.
	//
	// @tg http-method=GET
	// @tg http-path=`/todos/:id`
	// @tg http-args=id|id|explicit
	// @tg http-headers=lkId|x-lk-id|explicit
	// @tg enableInlineSingle
	// @tg summary=`Get a todo by id`
	// @tg id.desc=`Todo id`
	// @tg lkId.desc=`Cabinet id, supplied via the x-lk-id header`
	// @tg lkId.required
	Get(ctx context.Context, lkId int64, id int64) (todo dto.Todo, err error)

	// Update edits title/description and/or the completed flag of a todo.
	// All fields except id are optional (PATCH semantics): nil pointers keep
	// the existing value.
	//
	// @tg http-method=PATCH
	// @tg http-path=`/todos/:id`
	// @tg http-args=id|id|explicit
	// @tg enableInlineSingle
	// @tg summary=`Update a todo`
	// @tg id.desc=`Todo id`
	// @tg title.desc=`New title (optional)`
	// @tg description.desc=`New description (optional)`
	// @tg completed.desc=`New completed flag (optional)`
	Update(ctx context.Context, id int64, title *string, description *string, completed *bool) (todo dto.Todo, err error)

	// Delete removes a todo by id; idempotent miss returns 404.
	//
	// @tg http-method=DELETE
	// @tg http-path=`/todos/:id`
	// @tg http-args=id|id|explicit
	// @tg http-success=204
	// @tg summary=`Delete a todo`
	// @tg id.desc=`Todo id`
	Delete(ctx context.Context, id int64) (err error)

	// Toggle flips the completed flag of a todo and returns the updated item.
	//
	// @tg http-method=POST
	// @tg http-path=`/todos/:id/toggle`
	// @tg http-args=id|id|explicit
	// @tg enableInlineSingle
	// @tg summary=`Toggle todo completion`
	// @tg id.desc=`Todo id`
	Toggle(ctx context.Context, id int64) (todo dto.Todo, err error)
}
