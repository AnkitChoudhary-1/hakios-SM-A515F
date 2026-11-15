/* SPDX-License-Identifier: GPL-2.0 */
/* Native sanitizer guards for the exact core compiled into the Android module.
 * Successful state transitions below model the module; no physical allocation,
 * sysfs teardown, kernel locking or random-number source is tested here.
 */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ownership_core.h"
#include "arena_budget.h"

static unsigned int assertions, parser_cases, state_cases, layout_cases;
static const char token[] = "0123456789abcdef0123456789abcdef";
static const char plan[] = OP_PLAN_SHA;
static const struct op_region fixed_regions[] = { AR_LAYOUT };

#define CHECK(condition) do { \
	assertions++; \
	if (!(condition)) { \
		fprintf(stderr, "FAIL line=%u expression=%s\n", \
			(unsigned int)__LINE__, #condition); \
		exit(1); \
	} \
} while (0)

static unsigned int request_text(char *buffer, const char *action,
				 const char *sequence)
{
	int count = snprintf(buffer, OP_REQUEST_MAX + 16, "%s:%s:%s:%s",
			     action, token, plan, sequence);
	CHECK(count > 0 && count < (int)(OP_REQUEST_MAX + 16));
	return (unsigned int)count;
}

static void parse_case(const char *value, unsigned int count,
			 enum op_result expected)
{
	struct op_request request;
	memset(&request, 0xa5, sizeof(request));
	parser_cases++;
	CHECK(op_parse(value, count, &request) == expected);
}

static void parser_guards(void)
{
	char buffer[OP_REQUEST_MAX + 16], changed[OP_REQUEST_MAX + 16];
	struct op_request request;
	unsigned int count, i, j;
	static const char *valid_sequences[] = { "1", "9", "10", "65535" };
	static const char *bad_sequences[] = {
		"", "0", "01", "00001", "-1", "+1", " 1", "1 ", "1\t",
		"65536", "99999", "100000", "4294967296", "1:2", "1\r"
	};
	for (j = 0; j < 2; j++) {
		const char *action = j ? "release" : "bind";
		for (i = 0; i < sizeof(valid_sequences) / sizeof(valid_sequences[0]); i++) {
			count = request_text(buffer, action, valid_sequences[i]);
			parse_case(buffer, count, OP_OK);
			CHECK(op_parse(buffer, count, &request) == OP_OK);
			CHECK(request.action == (j ? OP_RELEASE : OP_BIND));
			CHECK(request.seq == (unsigned int)strtoul(valid_sequences[i], NULL, 10));
			CHECK(strcmp(request.token, token) == 0);
			CHECK(strcmp(request.plan, plan) == 0);
			buffer[count++] = '\n';
			parse_case(buffer, count, OP_OK);
		}
		for (i = 0; i < sizeof(bad_sequences) / sizeof(bad_sequences[0]); i++) {
			count = request_text(buffer, action, bad_sequences[i]);
			parse_case(buffer, count, OP_MALFORMED);
		}
		count = request_text(buffer, action, "1");
		/* Every truncated form of the shortest valid message must fail. */
		for (i = 0; i < count; i++)
			parse_case(buffer, i, OP_MALFORMED);
		/* Every byte is required; embedded NUL is never a terminator. */
		for (i = 0; i < count; i++) {
			memcpy(changed, buffer, count);
			changed[i] = 0;
			parse_case(changed, count, OP_MALFORMED);
		}
		for (i = j ? 8 : 5; i < count - 2; i++) {
			memcpy(changed, buffer, count);
			changed[i] = 'G';
			parse_case(changed, count, OP_MALFORMED);
		}
		/* Exact-size, unterminated input checks the explicit-count boundary. */
		{
			char *exact = malloc(count);
			CHECK(exact != NULL);
			memcpy(exact, buffer, count);
			parse_case(exact, count, OP_OK);
			free(exact);
		}
		memcpy(changed, buffer, count);
		changed[count] = 0;
		parse_case(changed, count + 1, OP_MALFORMED);
		changed[count] = '\n';
		changed[count + 1] = '\n';
		parse_case(changed, count + 2, OP_MALFORMED);
		changed[count + 1] = 'x';
		parse_case(changed, count + 2, OP_MALFORMED);
	}
	parse_case(NULL, 1, OP_MALFORMED);
	CHECK(op_parse(buffer, 1, NULL) == OP_MALFORMED);
	memset(changed, 'a', sizeof(changed));
	parse_case(changed, OP_REQUEST_MAX + 1, OP_MALFORMED);
	parse_case(changed, UINT_MAX, OP_MALFORMED);
	/* Bounded arbitrary byte inputs exercise failed-prefix/read bounds under
	 * ASan/UBSan. The alphabet cannot construct a valid request by accident. */
	for (i = 1; i <= OP_REQUEST_MAX; i++) {
		char *exact = malloc(i);
		CHECK(exact != NULL);
		for (j = 0; j < i; j++)
			exact[j] = (char)((i * 17U + j * 31U) & 31U);
		parse_case(exact, i, OP_MALFORMED);
		free(exact);
	}
}

static struct op_state fresh_state(void)
{
	struct op_state state;
	memset(&state, 0, sizeof(state));
	memcpy(state.token, token, sizeof(token));
	memcpy(state.plan, plan, sizeof(plan));
	state.active = 1;
	return state;
}

static struct op_request valid_request(enum op_action action, unsigned int seq)
{
	struct op_request request;
	memset(&request, 0, sizeof(request));
	memcpy(request.token, token, sizeof(token));
	memcpy(request.plan, plan, sizeof(plan));
	request.action = action;
	request.seq = seq;
	return request;
}

static void state_case(const struct op_state *state,
			 const struct op_request *request, enum op_result expected)
{
	struct op_state before_state = *state;
	struct op_request before_request = *request;
	state_cases++;
	CHECK(op_check(state, request) == expected);
	/* Core validation never mutates ownership or sequence on any outcome. */
	CHECK(memcmp(state, &before_state, sizeof(*state)) == 0);
	CHECK(memcmp(request, &before_request, sizeof(*request)) == 0);
}

static void state_guards(void)
{
	struct op_state state = fresh_state(), changed;
	struct op_request request = valid_request(OP_BIND, 1), bad;
	unsigned int i;
	state_case(&state, &request, OP_OK);
	/* Model successful first binding: an old seq cannot be used again. */
	state.bound = 1;
	state.last_seq = 1;
	state_case(&state, &request, OP_STALE);
	request.seq = 3;
	state_case(&state, &request, OP_STALE);
	request.seq = 2;
	state_case(&state, &request, OP_OK);
	request.action = OP_RELEASE;
	state_case(&state, &request, OP_OK);
	/* Model explicit release, including revocation before physical free. */
	state.last_seq = 2;
	state.active = 0;
	state.bound = 0;
	request.seq = 3;
	state_case(&state, &request, OP_INACTIVE);
	request.action = OP_BIND;
	state_case(&state, &request, OP_INACTIVE);
	state = fresh_state();
	request = valid_request(OP_BIND, 1);
	for (i = 0; i < OP_TOKEN_LEN; i++) {
		changed = state;
		changed.token[i] = changed.token[i] == 'a' ? 'b' : 'a';
		/* A new module/boot lifetime with a different token rejects the old
		 * request even if the physical address and host run ID are reused. */
		state_case(&changed, &request, OP_TOKEN);
	}
	for (i = 0; i < OP_PLAN_LEN; i++) {
		bad = request;
		bad.plan[i] = bad.plan[i] == 'a' ? 'b' : 'a';
		state_case(&state, &bad, OP_PLAN);
	}
	changed = state;
	changed.token[OP_TOKEN_LEN] = 'x';
	state_case(&changed, &request, OP_TOKEN);
	bad = request;
	bad.token[OP_TOKEN_LEN] = 'x';
	state_case(&state, &bad, OP_TOKEN);
	changed = state;
	changed.plan[OP_PLAN_LEN] = 'x';
	state_case(&changed, &request, OP_PLAN);
	bad = request;
	bad.plan[OP_PLAN_LEN] = 'x';
	state_case(&state, &bad, OP_PLAN);
	bad = request;
	bad.action = (enum op_action)0;
	state_case(&state, &bad, OP_MALFORMED);
	bad.action = (enum op_action)3;
	state_case(&state, &bad, OP_MALFORMED);
	bad = request;
	bad.seq = 0;
	state_case(&state, &bad, OP_STALE);
	bad.seq = 65536;
	state_case(&state, &bad, OP_STALE);
	bad.seq = UINT_MAX;
	state_case(&state, &bad, OP_STALE);
	state.last_seq = 65534;
	request.seq = 65535;
	state_case(&state, &request, OP_OK);
	state.last_seq = 65535;
	state_case(&state, &request, OP_STALE);
	state.last_seq = UINT_MAX;
	request.seq = 1;
	state_case(&state, &request, OP_STALE);
}

static void layout_case(const struct op_region *regions, unsigned int count,
			unsigned long bytes, unsigned long base, enum op_result expected)
{
	layout_cases++;
	CHECK(op_layout(regions, count, bytes, base) == expected);
}

static void layout_guards(void)
{
	struct op_region changed[6];
	unsigned int i;
	layout_case(fixed_regions, 6, AR_BYTES, 0, OP_OK);
	layout_case(fixed_regions, 6, AR_BYTES, 0x81980000UL, OP_OK);
	layout_case(fixed_regions, 6, AR_BYTES,
		    (ULONG_MAX & ~65535UL) - 65536UL, OP_OK);
	layout_case(fixed_regions, 6, AR_BYTES, ULONG_MAX & ~65535UL, OP_LAYOUT);
	layout_case(fixed_regions, 6, AR_BYTES, ULONG_MAX, OP_LAYOUT);
	layout_case(fixed_regions, 6, AR_BYTES, 4096, OP_LAYOUT);
	layout_case(NULL, 6, AR_BYTES, 0, OP_LAYOUT);
	layout_case(fixed_regions, 5, AR_BYTES, 0, OP_LAYOUT);
	layout_case(fixed_regions, 7, AR_BYTES, 0, OP_LAYOUT);
	layout_case(fixed_regions, 6, 0, 0, OP_LAYOUT);
	layout_case(fixed_regions, 6, 65535, 0, OP_LAYOUT);
	layout_case(fixed_regions, 6, 65537, 0, OP_LAYOUT);
	layout_case(fixed_regions, 6, ULONG_MAX, 0, OP_LAYOUT);
	for (i = 0; i < 6; i++) {
		memcpy(changed, fixed_regions, sizeof(changed));
		changed[i].start++;
		layout_case(changed, 6, AR_BYTES, 0, OP_LAYOUT);
		memcpy(changed, fixed_regions, sizeof(changed));
		changed[i].size = 0;
		layout_case(changed, 6, AR_BYTES, 0, OP_LAYOUT);
		changed[i].size = ULONG_MAX;
		layout_case(changed, 6, AR_BYTES, 0, OP_LAYOUT);
		memcpy(changed, fixed_regions, sizeof(changed));
		changed[i].size++;
		layout_case(changed, 6, AR_BYTES, 0, OP_LAYOUT);
		memcpy(changed, fixed_regions, sizeof(changed));
		changed[i].size += 4096;
		layout_case(changed, 6, AR_BYTES, 0, OP_LAYOUT);
		memcpy(changed, fixed_regions, sizeof(changed));
		changed[i].start = ULONG_MAX;
		layout_case(changed, 6, AR_BYTES, 0, OP_LAYOUT);
	}
	memcpy(changed, fixed_regions, sizeof(changed));
	changed[5].size -= 4096;
	layout_case(changed, 6, AR_BYTES, 0, OP_LAYOUT);
	/* A valid full partition remains valid after redistribution. The fixed
	 * plan digest/source binding, not this arithmetic guard, pins our budget. */
	memcpy(changed, fixed_regions, sizeof(changed));
	changed[0].size += 4096;
	changed[1].start += 4096;
	changed[1].size -= 4096;
	layout_case(changed, 6, AR_BYTES, 0, OP_OK);
}

int main(void)
{
	parser_guards();
	state_guards();
	layout_guards();
	printf("OWNERSHIP_CORE_GUARDS assertions=%u parser_cases=%u state_cases=%u layout_cases=%u\n",
	       assertions, parser_cases, state_cases, layout_cases);
	return 0;
}
