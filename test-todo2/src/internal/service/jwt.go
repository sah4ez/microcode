package service

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/loki/todoservice/contracts/dto"
	"github.com/loki/todoservice/internal/storage"
)

// JWT config from environment.
var (
	authSecret     string
	authAccessTTL  time.Duration
	authRefreshTTL time.Duration
)

// refreshTokens tracks valid refresh token JTIs in-memory.
var refreshTokens sync.Map

func init() {
	authSecret = os.Getenv("AUTH_SECRET")
	if authSecret == "" {
		b := make([]byte, 32)
		if _, err := rand.Read(b); err != nil {
			panic("generate default auth secret: " + err.Error())
		}
		authSecret = hex.EncodeToString(b)
	}
	if v := os.Getenv("AUTH_ACCESS_TTL"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			authAccessTTL = d
		}
	}
	if authAccessTTL == 0 {
		authAccessTTL = 15 * time.Minute
	}
	if v := os.Getenv("AUTH_REFRESH_TTL"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			authRefreshTTL = d
		}
	}
	if authRefreshTTL == 0 {
		authRefreshTTL = 7 * 24 * time.Hour
	}
}

// Claims are the JWT custom claims for both access and refresh tokens.
type Claims struct {
	UserID int64 `json:"user_id"`
	jwt.RegisteredClaims
}

// GenerateTokenPair creates an access + refresh JWT pair for the given user.
func GenerateTokenPair(userID int64) (dto.TokenPair, error) {
	now := time.Now()
	accessExp := now.Add(authAccessTTL)
	refreshExp := now.Add(authRefreshTTL)

	accessToken := jwt.NewWithClaims(jwt.SigningMethodHS256, Claims{
		UserID: userID,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(accessExp),
			IssuedAt:  jwt.NewNumericDate(now),
		},
	})
	accessStr, err := accessToken.SignedString([]byte(authSecret))
	if err != nil {
		return dto.TokenPair{}, fmt.Errorf("sign access token: %w", err)
	}

	refreshJTI := make([]byte, 16)
	if _, err := rand.Read(refreshJTI); err != nil {
		return dto.TokenPair{}, fmt.Errorf("generate refresh jti: %w", err)
	}
	jtiStr := hex.EncodeToString(refreshJTI)
	refreshToken := jwt.NewWithClaims(jwt.SigningMethodHS256, Claims{
		UserID: userID,
		RegisteredClaims: jwt.RegisteredClaims{
			ID:        jtiStr,
			ExpiresAt: jwt.NewNumericDate(refreshExp),
			IssuedAt:  jwt.NewNumericDate(now),
		},
	})
	refreshStr, err := refreshToken.SignedString([]byte(authSecret))
	if err != nil {
		return dto.TokenPair{}, fmt.Errorf("sign refresh token: %w", err)
	}

	refreshTokens.Store(jtiStr, refreshExp)
	return dto.TokenPair{AccessToken: accessStr, RefreshToken: refreshStr}, nil
}

// ParseAndValidateToken parses a JWT string and returns the claims.
func ParseAndValidateToken(tokenStr string) (*Claims, error) {
	token, err := jwt.ParseWithClaims(tokenStr, &Claims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return []byte(authSecret), nil
	})
	if err != nil {
		return nil, fmt.Errorf("parse token: %w", err)
	}
	claims, ok := token.Claims.(*Claims)
	if !ok || !token.Valid {
		return nil, errors.New("invalid token")
	}
	return claims, nil
}

// ParseAndValidateRefreshToken parses a refresh JWT and checks JTI validity.
func ParseAndValidateRefreshToken(tokenStr string) (*Claims, error) {
	claims, err := ParseAndValidateToken(tokenStr)
	if err != nil {
		return nil, err
	}
	jti := claims.ID
	if jti == "" {
		return nil, errors.New("refresh token missing jti")
	}
	if _, ok := refreshTokens.Load(jti); !ok {
		return nil, errors.New("refresh token revoked")
	}
	return claims, nil
}

// RevokeRefreshToken removes a refresh token JTI from the valid set.
func RevokeRefreshToken(jti string) {
	refreshTokens.Delete(jti)
}

// ExtractBearerToken extracts the Bearer token from the Authorization header.
func ExtractBearerToken(authHeader string) (string, error) {
	if authHeader == "" {
		return "", ErrUnauthorized
	}
	parts := strings.SplitN(authHeader, " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "bearer") {
		return "", ErrInvalidToken
	}
	return strings.TrimSpace(parts[1]), nil
}

// CleanExpiredRefreshTokens removes expired JTIs from the in-memory store.
func CleanExpiredRefreshTokens() {
	now := time.Now()
	refreshTokens.Range(func(key, value any) bool {
		if exp, ok := value.(time.Time); ok && now.After(exp) {
			refreshTokens.Delete(key)
		}
		return true
	})
}
