package usecase

import (
	"context"
	"mime/multipart"

	"github.com/redis/go-redis/v9"
	"github.com/medscribe/services/api/internal/entity"
)

type mockSessionRepo struct {
	createFn          func(context.Context, *entity.Session) (*entity.Session, error)
	getByIDFn         func(context.Context, string) (*entity.Session, error)
	updateFn          func(context.Context, *entity.Session) (*entity.Session, error)
	listByDoctorFn    func(context.Context, string, int, int) ([]*entity.Session, error)
	getDocumentsFn    func(context.Context, string) ([]*entity.Document, error)
	getQueueFn        func(context.Context, string) ([]*entity.QueueItem, error)
	updateQueueItemFn func(context.Context, string, string, string) (*entity.QueueItem, error)
	getRecordFn       func(context.Context, string) (*entity.MedicalRecord, error)
}

func (m *mockSessionRepo) Create(ctx context.Context, s *entity.Session) (*entity.Session, error) {
	if m.createFn != nil {
		return m.createFn(ctx, s)
	}
	return s, nil
}

func (m *mockSessionRepo) GetByID(ctx context.Context, id string) (*entity.Session, error) {
	if m.getByIDFn != nil {
		return m.getByIDFn(ctx, id)
	}
	return nil, entity.ErrNotFound
}

func (m *mockSessionRepo) Update(ctx context.Context, s *entity.Session) (*entity.Session, error) {
	if m.updateFn != nil {
		return m.updateFn(ctx, s)
	}
	return s, nil
}

func (m *mockSessionRepo) ListByDoctor(ctx context.Context, doctorID string, limit, offset int) ([]*entity.Session, error) {
	if m.listByDoctorFn != nil {
		return m.listByDoctorFn(ctx, doctorID, limit, offset)
	}
	return nil, nil
}

func (m *mockSessionRepo) GetDocuments(ctx context.Context, sessionID string) ([]*entity.Document, error) {
	if m.getDocumentsFn != nil {
		return m.getDocumentsFn(ctx, sessionID)
	}
	return nil, nil
}

func (m *mockSessionRepo) GetQueue(ctx context.Context, sessionID string) ([]*entity.QueueItem, error) {
	if m.getQueueFn != nil {
		return m.getQueueFn(ctx, sessionID)
	}
	return nil, nil
}

func (m *mockSessionRepo) UpdateQueueItem(ctx context.Context, sessionID, itemID, status string) (*entity.QueueItem, error) {
	if m.updateQueueItemFn != nil {
		return m.updateQueueItemFn(ctx, sessionID, itemID, status)
	}
	return nil, entity.ErrNotFound
}

func (m *mockSessionRepo) GetRecord(ctx context.Context, sessionID string) (*entity.MedicalRecord, error) {
	if m.getRecordFn != nil {
		return m.getRecordFn(ctx, sessionID)
	}
	return nil, entity.ErrNotFound
}

type mockUserRepo struct {
	createFn          func(context.Context, *entity.User) (*entity.User, error)
	getByIDFn         func(context.Context, string) (*entity.User, error)
	getByEmailFn      func(context.Context, string) (*entity.User, error)
	getByUsernameFn   func(context.Context, string) (*entity.User, error)
	updateLastLoginFn func(context.Context, string) error
}

func (m *mockUserRepo) Create(ctx context.Context, u *entity.User) (*entity.User, error) {
	if m.createFn != nil {
		return m.createFn(ctx, u)
	}
	return u, nil
}

func (m *mockUserRepo) GetByID(ctx context.Context, id string) (*entity.User, error) {
	if m.getByIDFn != nil {
		return m.getByIDFn(ctx, id)
	}
	return nil, entity.ErrNotFound
}

func (m *mockUserRepo) GetByEmail(ctx context.Context, email string) (*entity.User, error) {
	if m.getByEmailFn != nil {
		return m.getByEmailFn(ctx, email)
	}
	return nil, entity.ErrNotFound
}

func (m *mockUserRepo) GetByUsername(ctx context.Context, username string) (*entity.User, error) {
	if m.getByUsernameFn != nil {
		return m.getByUsernameFn(ctx, username)
	}
	return nil, entity.ErrNotFound
}

func (m *mockUserRepo) UpdateLastLogin(ctx context.Context, userID string) error {
	if m.updateLastLoginFn != nil {
		return m.updateLastLoginFn(ctx, userID)
	}
	return nil
}

type mockPatientRepo struct {
	createFn         func(context.Context, *entity.Patient) (*entity.Patient, error)
	getByIDFn        func(context.Context, string) (*entity.Patient, error)
	getByMRNFn       func(context.Context, string) (*entity.Patient, error)
	updateFn         func(context.Context, *entity.Patient) (*entity.Patient, error)
	listFn           func(context.Context, int, int) ([]*entity.Patient, error)
	searchFn         func(context.Context, string, int) ([]*entity.Patient, error)
	historyRecordsFn func(context.Context, string, int, int) ([]*entity.MedicalRecord, error)
}

func (m *mockPatientRepo) Create(ctx context.Context, p *entity.Patient) (*entity.Patient, error) {
	if m.createFn != nil {
		return m.createFn(ctx, p)
	}
	return p, nil
}

func (m *mockPatientRepo) GetByID(ctx context.Context, id string) (*entity.Patient, error) {
	if m.getByIDFn != nil {
		return m.getByIDFn(ctx, id)
	}
	return nil, entity.ErrNotFound
}

func (m *mockPatientRepo) GetByMRN(ctx context.Context, mrn string) (*entity.Patient, error) {
	if m.getByMRNFn != nil {
		return m.getByMRNFn(ctx, mrn)
	}
	return nil, entity.ErrNotFound
}

func (m *mockPatientRepo) Update(ctx context.Context, p *entity.Patient) (*entity.Patient, error) {
	if m.updateFn != nil {
		return m.updateFn(ctx, p)
	}
	return p, nil
}

func (m *mockPatientRepo) List(ctx context.Context, limit, offset int) ([]*entity.Patient, error) {
	if m.listFn != nil {
		return m.listFn(ctx, limit, offset)
	}
	return nil, nil
}

func (m *mockPatientRepo) Search(ctx context.Context, query string, limit int) ([]*entity.Patient, error) {
	if m.searchFn != nil {
		return m.searchFn(ctx, query, limit)
	}
	return nil, nil
}

func (m *mockPatientRepo) HistoryRecords(ctx context.Context, patientID string, limit, offset int) ([]*entity.MedicalRecord, error) {
	if m.historyRecordsFn != nil {
		return m.historyRecordsFn(ctx, patientID, limit, offset)
	}
	return nil, nil
}

type mockPublisher struct {
	publishJSONFn func(context.Context, string, string, any) error
}

func (m *mockPublisher) PublishJSON(ctx context.Context, topic, key string, v any) error {
	if m.publishJSONFn != nil {
		return m.publishJSONFn(ctx, topic, key, v)
	}
	return nil
}

type mockRedis struct {
	getFn func(context.Context, string) *redis.StringCmd
	setFn func(context.Context, string, any, interface{}) *redis.StatusCmd
}

func (m *mockRedis) Get(ctx context.Context, key string) *redis.StringCmd {
	if m.getFn != nil {
		return m.getFn(ctx, key)
	}
	cmd := redis.NewStringCmd(ctx)
	cmd.SetErr(redis.Nil)
	return cmd
}

func (m *mockRedis) Set(ctx context.Context, key string, value interface{}, expiration interface{}) *redis.StatusCmd {
	if m.setFn != nil {
		return m.setFn(ctx, key, value, expiration)
	}
	cmd := redis.NewStatusCmd(ctx)
	cmd.SetVal("OK")
	return cmd
}

type fakeMultipartFile struct{}

func (f fakeMultipartFile) Read(_ []byte) (n int, err error)  { return 0, nil }
func (f fakeMultipartFile) Close() error                      { return nil }
func (f fakeMultipartFile) Seek(_ int64, _ int) (int64, error) { return 0, nil }
func (f fakeMultipartFile) ReadAt(_ []byte, _ int64) (n int, err error) {
	return 0, nil
}

func newFileHeader(name string) *multipart.FileHeader {
	return &multipart.FileHeader{Filename: name}
}
