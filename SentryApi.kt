import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface SentryApi {
    @GET("health")
    suspend fun health(): HealthResponse

    @POST("users")
    suspend fun createUser(@Body request: UserCreate): User

    @GET("users/{userId}")
    suspend fun getUser(@Path("userId") userId: Int): User

    @POST("logs")
    suspend fun createLog(@Body request: SymptomLogCreate): SymptomLog

    @GET("logs/{userId}")
    suspend fun listLogs(@Path("userId") userId: Int): List<SymptomLog>

    @GET("insights/{userId}")
    suspend fun getInsights(@Path("userId") userId: Int): InsightsResponse

    @POST("alerts/check")
    suspend fun checkAlert(@Body request: AlertCheckRequest): AlertResponse
}

data class HealthResponse(
    val status: String,
    val time: String,
)

data class UserCreate(
    val name: String,
    val condition: String,
)

data class User(
    val id: Int,
    val name: String,
    val condition: String,
    val created_at: String,
)

data class SymptomLogCreate(
    val user_id: Int,
    val is_flare: Boolean = true,
    val severity: Int? = null,
    val notes: String? = null,
    val latitude: Double,
    val longitude: Double,
    val logged_at: String? = null,
)

data class SymptomLog(
    val id: Int,
    val user_id: Int,
    val is_flare: Boolean,
    val severity: Int?,
    val notes: String?,
    val latitude: Double,
    val longitude: Double,
    val logged_at: String,
    val temperature_c: Double?,
    val humidity_pct: Double?,
    val pressure_hpa: Double?,
    val pm2_5: Double?,
    val pm10: Double?,
    val us_aqi: Double?,
)

data class InsightsResponse(
    val user_id: Int,
    val total_flare_logs: Int,
    val total_baseline_logs: Int,
    val insights: List<TriggerInsight>,
    val message: String,
)

data class TriggerInsight(
    val id: Int,
    val factor: String,
    val direction: String,
    val threshold: Double,
    val confidence_pct: Double,
    val support_count: Int,
    val human_summary: String,
    val computed_at: String,
)

data class AlertCheckRequest(
    val user_id: Int,
    val latitude: Double,
    val longitude: Double,
)

data class AlertResponse(
    val user_id: Int,
    val at_risk: Boolean,
    val triggered_factors: List<String>,
    val message: String,
    val current_conditions: Map<String, Double?>,
)
