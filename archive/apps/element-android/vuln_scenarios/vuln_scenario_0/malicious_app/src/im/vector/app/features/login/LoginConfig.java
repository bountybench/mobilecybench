package im.vector.app.features.login;

import android.os.Parcel;
import android.os.Parcelable;

public class LoginConfig implements Parcelable {
    private final String homeServerUrl;
    private final String identityServerUrl;

    public LoginConfig(String homeServerUrl, String identityServerUrl) {
        this.homeServerUrl = homeServerUrl;
        this.identityServerUrl = identityServerUrl;
    }

    protected LoginConfig(Parcel in) {
        this.homeServerUrl = in.readString();
        this.identityServerUrl = in.readString();
    }

    public static final Creator<LoginConfig> CREATOR = new Creator<LoginConfig>() {
        @Override
        public LoginConfig createFromParcel(Parcel in) {
            return new LoginConfig(in);
        }

        @Override
        public LoginConfig[] newArray(int size) {
            return new LoginConfig[size];
        }
    };

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel dest, int flags) {
        dest.writeString(homeServerUrl);
        dest.writeString(identityServerUrl);
    }

    public String getHomeServerUrl() {
        return homeServerUrl;
    }

    public String getIdentityServerUrl() {
        return identityServerUrl;
    }
}
