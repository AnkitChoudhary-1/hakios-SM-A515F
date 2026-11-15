/* SPDX-License-Identifier: GPL-2.0 */
/* Shared request/state guards. Caller serializes the complete allocation use. */
#ifndef HAKIOS_OWNERSHIP_CORE_H
#define HAKIOS_OWNERSHIP_CORE_H

#define OP_TOKEN_LEN 32U
#define OP_PLAN_LEN 64U
#define OP_REQUEST_MAX 128U
enum op_action { OP_BIND = 1, OP_RELEASE = 2 };
enum op_result { OP_OK, OP_MALFORMED, OP_TOKEN, OP_PLAN, OP_STALE,
	OP_INACTIVE, OP_LAYOUT };
struct op_request {
	enum op_action action;
	char token[OP_TOKEN_LEN + 1], plan[OP_PLAN_LEN + 1];
	unsigned int seq;
};
struct op_state {
	char token[OP_TOKEN_LEN + 1], plan[OP_PLAN_LEN + 1];
	unsigned int last_seq;
	int active, bound;
};
struct op_region { unsigned long start, size; unsigned char pattern; };

static int op_hex(char c)
{
	return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
}
static int op_equal(const char *a, const char *b, unsigned int n)
{
	unsigned int i;
	for (i = 0; i < n; i++)
		if (a[i] != b[i])
			return 0;
	return a[n] == 0 && b[n] == 0;
}
/* Exact grammar: bind|release : 32 lower hex : 64 lower hex : seq 1..65535.
 * Optional one terminal newline, no whitespace, signs, leading zero or suffix.
 * Explicit byte length; no reliance on NUL termination or bytes outside count.
 */
static enum op_result op_parse(const char *value, unsigned int len,
				struct op_request *out)
{
	unsigned int i, pos, seq = 0, digits = 0;
	if (!value || !out)
		return OP_MALFORMED;
	if (len > OP_REQUEST_MAX || !len)
		return OP_MALFORMED;
	if (value[len - 1] == '\n')
		len--;
	if (len >= 5 && value[0] == 'b' && value[1] == 'i' &&
	    value[2] == 'n' && value[3] == 'd' && value[4] == ':') {
		out->action = OP_BIND;
		pos = 5;
	} else if (len >= 8 && value[0] == 'r' && value[1] == 'e' &&
		value[2] == 'l' && value[3] == 'e' && value[4] == 'a' &&
		value[5] == 's' && value[6] == 'e' && value[7] == ':') {
		out->action = OP_RELEASE;
		pos = 8;
	} else {
		return OP_MALFORMED;
	}
	if (len < pos + OP_TOKEN_LEN + 1 + OP_PLAN_LEN + 2)
		return OP_MALFORMED;
	for (i = 0; i < OP_TOKEN_LEN; i++) {
		if (!op_hex(value[pos + i]))
			return OP_MALFORMED;
		out->token[i] = value[pos + i];
	}
	out->token[OP_TOKEN_LEN] = 0;
	pos += OP_TOKEN_LEN;
	if (value[pos++] != ':')
		return OP_MALFORMED;
	for (i = 0; i < OP_PLAN_LEN; i++) {
		if (!op_hex(value[pos + i]))
			return OP_MALFORMED;
		out->plan[i] = value[pos + i];
	}
	out->plan[OP_PLAN_LEN] = 0;
	pos += OP_PLAN_LEN;
	if (value[pos++] != ':' || pos >= len || value[pos] < '1' || value[pos] > '9')
		return OP_MALFORMED;
	for (; pos < len; pos++) {
		if (value[pos] < '0' || value[pos] > '9' || ++digits > 5)
			return OP_MALFORMED;
		seq = seq * 10 + (unsigned int)(value[pos] - '0');
	}
	if (!digits || seq > 65535)
		return OP_MALFORMED;
	out->seq = seq;
	return OP_OK;
}
static enum op_result op_check(const struct op_state *state,
				 const struct op_request *request)
{
	if (request->action != OP_BIND && request->action != OP_RELEASE)
		return OP_MALFORMED;
	if (!op_equal(state->token, request->token, OP_TOKEN_LEN))
		return OP_TOKEN;
	if (!op_equal(state->plan, request->plan, OP_PLAN_LEN))
		return OP_PLAN;
	if (!state->active)
		return OP_INACTIVE;
	if (!request->seq || request->seq > 65535 ||
	    state->last_seq >= 65535 || request->seq != state->last_seq + 1)
		return OP_STALE;
	return OP_OK;
}
/* Validate the full fixed partition before computing any address or writing. */
static enum op_result op_layout(const struct op_region *regions,
	unsigned int count, unsigned long bytes, unsigned long base)
{
	unsigned long end = 0;
	unsigned int r;
	if (!regions || count != 6 || bytes != 65536 || base > ~0UL - bytes ||
	    (base & (bytes - 1)))
		return OP_LAYOUT;
	for (r = 0; r < count; r++) {
		if (regions[r].start != end || !regions[r].size ||
		    regions[r].size > bytes - end ||
		    (regions[r].start & 4095UL) || (regions[r].size & 4095UL))
			return OP_LAYOUT;
		end += regions[r].size;
	}
	return end == bytes ? OP_OK : OP_LAYOUT;
}
#endif
