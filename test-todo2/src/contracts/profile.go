package contracts

import (
	"context"

	"github.com/loki/todoservice/contracts/dto"
)

// PersonalProfileService is the contract group for managing личные кабинеты
// (personal cabinets / profiles, "ЛК"). Each cabinet owns an independent set of
// todos; the web UI lets the user switch between cabinets, and every todo
// create/get request carries the active cabinet's id in the `x-lk-id` header.
//
// @tg title=`Personal Profile Service`
// @tg version=`1.0.0`
// @tg desc=`CRUD for personal cabinets (ЛК) that own disjoint sets of todos.`
// @tg http-server
type PersonalProfileService interface {
	// Create stores a new cabinet and returns it with id/created_at.
	//
	// @tg http-method=POST
	// @tg http-path=`/personal-profile`
	// @tg http-success=201
	// @tg enableInlineSingle
	// @tg summary=`Create a personal cabinet`
	// @tg requestBodyDesc=`Name is required.`
	// @tg name.required
	// @tg name.desc=`Cabinet name (e.g. "работа", "дом")`
	Create(ctx context.Context, name string) (profile dto.PersonalProfile, err error)

	// List returns every cabinet.
	//
	// @tg http-method=GET
	// @tg http-path=`/personal-profile`
	// @tg summary=`List all cabinets`
	List(ctx context.Context) (profiles []dto.PersonalProfile, err error)

	// Get returns a single cabinet by id; ErrNotFound when missing.
	//
	// @tg http-method=GET
	// @tg http-path=`/personal-profile/:id`
	// @tg http-args=id|id|explicit
	// @tg enableInlineSingle
	// @tg summary=`Get a cabinet by id`
	// @tg id.desc=`Cabinet id`
	Get(ctx context.Context, id int64) (profile dto.PersonalProfile, err error)

	// Update edits the name of a cabinet (PATCH semantics: nil pointer keeps
	// the existing value).
	//
	// @tg http-method=PATCH
	// @tg http-path=`/personal-profile/:id`
	// @tg http-args=id|id|explicit
	// @tg enableInlineSingle
	// @tg summary=`Update a cabinet`
	// @tg id.desc=`Cabinet id`
	// @tg name.desc=`New name (optional)`
	Update(ctx context.Context, id int64, name *string) (profile dto.PersonalProfile, err error)

	// Delete removes a cabinet by id; idempotent miss returns 404.
	//
	// @tg http-method=DELETE
	// @tg http-path=`/personal-profile/:id`
	// @tg http-args=id|id|explicit
	// @tg http-success=204
	// @tg summary=`Delete a cabinet`
	// @tg id.desc=`Cabinet id`
	Delete(ctx context.Context, id int64) (err error)
}